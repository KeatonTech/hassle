# docs/COOKBOOK.md — Hassle cookbook

**Generated** by `hassle.docs.cookbook.generate_cookbook` from `fixtures/cookbook/` —
every recipe below is a real automation (or script) that compiles, validates against
the fixture registry, and has a passing simulator test in CI.
Do not hand-edit; regenerate via `hassle-dev docs --update`.

Copy a recipe's source into your bundle, then adjust the entity ids to match your
own `.hassle/registry.json`.


## 1. lights off at bedtime

`fixtures/cookbook/bundle/automations/bedtime_lights_off.py`

```python
"""Cookbook recipe 12: lights off at bedtime.

A single time trigger turns off every downstairs light in one action; a
`choose` decides whether to also arm the alarm depending on guest mode.
"""

from hassle import automation, choose, service, state, time, when


@automation(id="cookbook_bedtime_lights_off", alias="Cookbook: bedtime lights off")
def cookbook_bedtime_lights_off():
    when(time(at="23:00:00"))
    service("light.turn_off", entity_id=["light.living_room", "light.kitchen", "light.hallway"])
    with choose() as c:
        with c.when_(state("input_boolean.guest_mode").is_("off")):
            service(
                "alarm_control_panel.alarm_arm_home",
                target={"entity_id": "alarm_control_panel.home"},
            )
        with c.default():
            service(
                "notify.mobile_app_kai", message="Bedtime lights off (guest mode: alarm skipped)"
            )
```

## 2. door-left-open reminder

`fixtures/cookbook/bundle/automations/door_left_open_reminder.py`

```python
"""Cookbook recipe 7: door-left-open reminder.

`for_=` on a state trigger: only fires once the door has held "open" for
10 minutes straight (resets on any flap back to "closed").
"""

from hassle import automation, minutes, service, state, when


@automation(id="cookbook_door_left_open", alias="Cookbook: door left open")
def cookbook_door_left_open():
    when(state("binary_sensor.laundry_door").to("open", for_=minutes(10)))
    service("notify.mobile_app_kai", message="Laundry door has been open for 10 minutes")
```

## 3. template-based dynamic brightness

`fixtures/cookbook/bundle/automations/dynamic_brightness.py`

```python
"""Cookbook recipe 23: template-based dynamic brightness.

The template expression builder (DESIGN §5.4) computes a brightness value
from the outdoor temperature at compile time -- HA evaluates the resulting
Jinja string at runtime, the simulator's template engine evaluates it too.
"""

from hassle import automation, service, state, when


@automation(id="cookbook_dynamic_brightness", alias="Cookbook: dynamic brightness")
def cookbook_dynamic_brightness():
    when(state("binary_sensor.living_room_motion").to("on"))
    service(
        "light.turn_on",
        entity_id="light.living_room",
        brightness_pct=(state("sensor.outdoor_temperature").value < 10) * 30
        + (state("sensor.outdoor_temperature").value >= 10) * 80,
    )
```

## 4. fan on high temperature

`fixtures/cookbook/bundle/automations/fan_on_high_temperature.py`

```python
"""Cookbook recipe 11: fan on high temperature.

`numeric_state` crossing UP through a threshold turns the bedroom fan on.
"""

from hassle import automation, numeric_state, service, when


@automation(id="cookbook_fan_on_high_temp", alias="Cookbook: fan on high temp")
def cookbook_fan_on_high_temp():
    when(numeric_state("sensor.outdoor_temperature", above=28))
    service("fan.turn_on", target={"entity_id": "fan.bedroom"})
```

## 5. good-morning scene via a `@shared_script`

`fixtures/cookbook/bundle/automations/good_morning_scene.py`

```python
"""Cookbook recipe 8: good-morning scene via a `@shared_script`.

`good_morning` becomes a real HA script entity (visible/runnable/editable in
the HA UI); the automation's action list gets a `script.<id>`-style call, not
a re-run of the body (DESIGN §5.6).
"""

from hassle import automation, param, service, shared_script, state, when


@shared_script(id="cookbook_good_morning", alias="Good morning", icon="mdi:weather-sunny")
def cookbook_good_morning(brightness: int = 200):
    service("light.turn_on", entity_id="light.bedroom", brightness=param("brightness"))
    service("light.turn_on", entity_id="light.kitchen", brightness=param("brightness"))


@automation(id="cookbook_good_morning_trigger", alias="Cookbook: good morning trigger")
def cookbook_good_morning_trigger():
    when(state("input_boolean.armed").to("off"))
    cookbook_good_morning(brightness=180)
```

## 6. guest arrival, several things at once

`fixtures/cookbook/bundle/automations/guest_arrival_parallel.py`

```python
"""Cookbook recipe 21: guest arrival, several things at once.

`parallel()` runs a notify and two light calls concurrently instead of one
after another (DESIGN §5.5) -- useful when order truly doesn't matter and
you don't want one slow step to delay the rest.
"""

from hassle import automation, parallel, service, state, when


@automation(id="cookbook_guest_arrival_parallel", alias="Cookbook: guest arrival (parallel)")
def cookbook_guest_arrival_parallel():
    when(state("input_boolean.guest_mode").to("on"))
    with parallel():
        service("light.turn_on", target={"entity_id": "light.living_room"})
        service("light.turn_on", target={"entity_id": "light.hallway"})
        service("notify.mobile_app_kai", message="Guest mode enabled")
```

## 7. guest mode suppresses an automation

`fixtures/cookbook/bundle/automations/guest_mode_gate.py`

```python
"""Cookbook recipe 6: guest mode suppresses an automation.

`only_if` gating on an `input_boolean` helper -- the most common "quiet
hours"/"do not disturb" shape.
"""

from hassle import automation, only_if, service, state, when


@automation(id="cookbook_guest_mode_gate", alias="Cookbook: guest mode gate")
def cookbook_guest_mode_gate():
    when(state("binary_sensor.back_door").to("open"))
    only_if(state("input_boolean.guest_mode").is_("off"))
    service("notify.mobile_app_kai", message="Back door opened")
```

## 8. low-battery alert via a purpose-specific trigger

`fixtures/cookbook/bundle/automations/low_battery_alert.py`

```python
"""Cookbook recipe 10: low-battery alert via a purpose-specific trigger
(2026.7+, DESIGN §5.4).

`battery.became_low` is a purpose trigger type (not a classic numeric_state
threshold) -- the recipe an agent should reach for on a modern HA install.
"""

from hassle import automation, on, service, when


@automation(id="cookbook_low_battery_alert", alias="Cookbook: low battery alert")
def cookbook_low_battery_alert():
    when(on("battery.became_low", target="binary_sensor.laundry_door"))
    service("notify.mobile_app_kai", message="A sensor's battery is low")
```

## 9. motion light, night-only

`fixtures/cookbook/bundle/automations/motion_light.py`

```python
"""Cookbook recipe 1: motion light, night-only.

The canonical DESIGN §10.2 example: motion turns the hallway light on at
night, off again 5 minutes later, gated by guest mode and a sun condition.
"""

from hassle import automation, delay, only_if, service, state, sun, when


@automation(id="cookbook_motion_light", alias="Cookbook: motion light", mode="restart")
def cookbook_motion_light():
    when(state("binary_sensor.hall_motion").to("on"))
    only_if(state("input_boolean.guest_mode").is_("off"))
    only_if(sun(after="sunset", after_offset="-00:30:00"))
    service("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    delay(minutes=5)
    service("light.turn_off", entity_id="light.hallway")
```

## 10. multi-room motion lights via a compile-time loop + macro

`fixtures/cookbook/bundle/automations/multi_room_motion_lights.py`

```python
"""Cookbook recipe 22: multi-room motion lights via a compile-time loop + macro.

Python `for` at module scope generates one automation per room (DESIGN §5.5
metaprogramming-for-free); each one reuses the `notify_household` macro from
`lib/notify.py` (DESIGN §5.6) so the notification wording can never drift
between rooms.
"""

from lib.notify import notify_household

from hassle import automation, only_if, service, state, when

ROOMS = ["kitchen", "office"]

for room in ROOMS:

    @automation(id=f"cookbook_motion_{room}", alias=f"Cookbook: motion light ({room})")
    def _cookbook_motion(room: str = room) -> None:
        when(state(f"binary_sensor.{room}_motion").to("on"))
        only_if(state("input_boolean.guest_mode").is_("off"))
        service("light.turn_on", entity_id=f"light.{room}")
        notify_household(f"Motion detected in the {room}")
```

## 11. actionable mobile notification

`fixtures/cookbook/bundle/automations/notify_with_actions.py`

```python
"""Cookbook recipe 4: actionable mobile notification.

Sends an actionable notification with two buttons ("Open Blinds"/"Close
Blinds") and opens/closes the upstairs blinds depending on which one the
user taps -- built entirely on the `notify_mobile`/`action` recipe helpers
(`lib/notify_actions.py`), which are themselves built on the public
`capture_actions`/`emit_actions` seam (`hassle.compiler.recording`).
"""

from lib.notify_actions import action, notify_mobile

from hassle import automation, state, when
from hassle.services import cover


@automation(id="cookbook_notify_with_actions", alias="Cookbook: door unlocked notify")
def cookbook_notify_with_actions():
    when(state("lock.front_door").to("unlocked"))
    with notify_mobile(title="Front Door Unlocked", message="Adjust the upstairs blinds?"):
        with action("Open Blinds", icon="mdi:blinds-open"):
            cover.open_cover(target={"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]})
        with action("Close Blinds"):
            cover.close_cover(target={"entity_id": ["cover.bedroom_blinds", "cover.office_blinds"]})
```

## 12. presence-based away mode

`fixtures/cookbook/bundle/automations/presence_away_mode.py`

```python
"""Cookbook recipe 2: presence-based away mode.

Either phone leaving re-checks presence; `all_of` gates the action on BOTH
being away before arming, so a single phone leaving (while the other is
still home) does nothing.
"""

from hassle import all_of, automation, only_if, service, state, when


@automation(id="cookbook_presence_away", alias="Cookbook: everyone left")
def cookbook_presence_away():
    when(state("device_tracker.kai_phone").to("not_home"))
    when(state("device_tracker.john_phone").to("not_home"))
    only_if(
        all_of(
            state("device_tracker.kai_phone").is_("not_home"),
            state("device_tracker.john_phone").is_("not_home"),
        )
    )
    service("input_boolean.turn_on", target={"entity_id": "input_boolean.armed"})
```

## 13. purpose-trigger motion with an area target (2026.7+)

`fixtures/cookbook/bundle/automations/purpose_trigger_office_motion.py`

```python
"""Cookbook recipe 20: purpose-trigger motion with an area target (2026.7+).

`on("motion.detected", target=area(...))` -- the modern UI-default shape
(DESIGN §5.4) instead of a classic `state()` trigger on a specific sensor.
"""

from hassle import area, automation, minutes, on, service, when


@automation(id="cookbook_purpose_trigger_office_motion", alias="Cookbook: office motion (area)")
def cookbook_purpose_trigger_office_motion():
    when(on("motion.detected", target=area("office"), behavior="first", for_=minutes(1)))
    service("light.turn_on", target={"entity_id": "light.office_ceiling"})
```

## 14. repeat-flash the lights N times

`fixtures/cookbook/bundle/automations/repeat_flash_lights.py`

```python
"""Cookbook recipe 18: repeat-flash the lights N times.

`repeat_count` around a toggle+delay pair -- the classic "get my attention"
pattern (e.g. announcing a doorbell visually).
"""

from hassle import automation, delay, repeat_count, service, state, when


@automation(id="cookbook_repeat_flash_lights", alias="Cookbook: repeat flash lights")
def cookbook_repeat_flash_lights():
    when(state("binary_sensor.front_door").to("open"))
    with repeat_count(3):
        service("light.toggle", target={"entity_id": "light.hallway"})
        delay(seconds=1)
```

## 15. security check on arm

`fixtures/cookbook/bundle/automations/security_check_on_arm.py`

```python
"""Cookbook recipe 13: security check on arm.

When the house is armed, run a check across doors/locks and notify if
anything is left open/unlocked -- `all_of` combining several state
conditions inside a single `only_if`.
"""

from hassle import all_of, automation, only_if, service, state, when


@automation(id="cookbook_security_check_on_arm", alias="Cookbook: security check on arm")
def cookbook_security_check_on_arm():
    when(state("input_boolean.armed").to("on"))
    only_if(
        all_of(
            state("binary_sensor.back_door").is_("off"),
            state("lock.front_door").is_("locked"),
        )
    )
    service("notify.mobile_app_kai", message="Armed: all secure")
```

## 16. stop the automation early if a condition isn't met

`fixtures/cookbook/bundle/automations/stop_if_armed.py`

```python
"""Cookbook recipe 24: stop the automation early if a condition isn't met.

`stop(message, ...)` inside an `if_then` block ends the run right there
(distinct from `only_if`, which would skip the WHOLE automation before any
action ran) -- useful when you want the first action or two to always run,
then bail before the rest.
"""

from hassle import automation, if_then, service, state, stop, when


@automation(id="cookbook_stop_if_armed", alias="Cookbook: stop if armed")
def cookbook_stop_if_armed():
    when(state("binary_sensor.workshop_door").to("open"))
    service("light.turn_on", target={"entity_id": "light.workshop"})
    with if_then(state("input_boolean.armed").is_("on")):
        stop("Workshop is armed -- skipping the rest of the sequence")
    service("notify.mobile_app_kai", message="Workshop door opened (unarmed)")
```

## 17. sunset lights on

`fixtures/cookbook/bundle/automations/sunset_lights_on.py`

```python
"""Cookbook recipe 15: sunset lights on.

A `sun` trigger (not a condition, this time) turns the porch light on at
dusk.
"""

from hassle import automation, service, sun, when


@automation(id="cookbook_sunset_lights_on", alias="Cookbook: sunset lights on")
def cookbook_sunset_lights_on():
    when(sun(event="sunset"))
    service("light.turn_on", target={"entity_id": "light.porch"})
```

## 18. thermostat schedule

`fixtures/cookbook/bundle/automations/thermostat_schedule.py`

```python
"""Cookbook recipe 3: thermostat schedule.

A daily time trigger sets the living-room thermostat back for the night.
"""

from hassle import automation, service, time, when


@automation(id="cookbook_thermostat_schedule", alias="Cookbook: night setback")
def cookbook_thermostat_schedule():
    when(time(at="22:00:00"))
    service(
        "climate.set_temperature",
        target={"entity_id": "climate.living_room"},
        temperature=18,
    )
```

## 19. timer-based reminder

`fixtures/cookbook/bundle/automations/timer_based_reminder.py`

```python
"""Cookbook recipe 14: timer-based reminder.

Starting the kitchen timer when the oven turns on, and notifying when it
finishes (a `timer.*` entity moves to `idle` when it completes or is
cancelled -- gated here on `armed` so a manual cancel doesn't also notify).
"""

from hassle import automation, only_if, service, state, when


@automation(id="cookbook_start_kitchen_timer", alias="Cookbook: start kitchen timer")
def cookbook_start_kitchen_timer():
    when(state("switch.washing_machine").to("on"))
    service("timer.start", target={"entity_id": "timer.kitchen"}, duration="00:45:00")


@automation(id="cookbook_kitchen_timer_done", alias="Cookbook: kitchen timer done")
def cookbook_kitchen_timer_done():
    when(state("timer.kitchen").to("idle"))
    only_if(state("input_boolean.armed").is_("on"))
    service("notify.mobile_app_kai", message="Kitchen timer finished")
```

## 20. daily vacuum run

`fixtures/cookbook/bundle/automations/vacuum_daily_schedule.py`

```python
"""Cookbook recipe 9: daily vacuum run.

A `time` trigger starting the downstairs vacuum every morning while everyone
is out (a second `only_if` gate).
"""

from hassle import automation, only_if, service, state, time, when


@automation(id="cookbook_vacuum_daily", alias="Cookbook: daily vacuum")
def cookbook_vacuum_daily():
    when(time(at="10:00:00"))
    only_if(state("input_boolean.armed").is_("on"))
    service("vacuum.start", target={"entity_id": "vacuum.downstairs"})
```

## 21. wait for the door to close, then remind to lock it

`fixtures/cookbook/bundle/automations/wait_then_lock_reminder.py`

```python
"""Cookbook recipe 19: wait for the door to close, then remind to lock it.

`wait_for` blocks the action sequence until the door closes (or times out);
`continue_on_timeout` lets the reminder still fire either way.
"""

from hassle import automation, service, state, wait_for, when


@automation(id="cookbook_wait_then_lock_reminder", alias="Cookbook: wait then lock reminder")
def cookbook_wait_then_lock_reminder():
    when(state("binary_sensor.front_door").to("open"))
    wait_for(
        state("binary_sensor.front_door").to("closed"),
        timeout="00:05:00",
        continue_on_timeout=True,
    )
    service("notify.mobile_app_kai", message="Don't forget to lock the front door")
```

## 22. washing-machine-done

`fixtures/cookbook/bundle/automations/washing_machine_done.py`

```python
"""Cookbook recipe 5: washing-machine-done.

`numeric_state` crossing DOWN through a low-power threshold (the machine
finished its cycle and drew almost no power) -- the "only fires on the
cross, not while already below" behavior DESIGN §10.1 calls out.
"""

from hassle import automation, numeric_state, service, when


@automation(id="cookbook_washing_machine_done", alias="Cookbook: washing machine done")
def cookbook_washing_machine_done():
    when(numeric_state("sensor.washing_machine_power", below=3))
    service("notify.mobile_app_kai", message="Washing machine finished")
```
