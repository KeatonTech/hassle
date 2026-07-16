"""COOKBOOK.md recipe tests: one test per recipe, each proving the
automation/script actually does what its docstring claims (DESIGN §12:
"each recipe = automation + passing test").

Compiled and simulated the same way `test_sim_example_bundle.py` does
(`hassle.testing.Simulator` directly over `compile_bundle(...)`) -- I5:
these tests execute compiled IR, never DSL Python.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle
from hassle.testing import Simulator

_BUNDLE = Path(__file__).resolve().parents[1]


def _sim() -> Simulator:
    return Simulator(compile_bundle(_BUNDLE))


# 1. motion light -----------------------------------------------------------


def test_motion_light_fires_at_night() -> None:
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:00")
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.hallway", brightness_pct=60)
    sim.advance(minutes=5)
    sim.assert_called("light.turn_off", entity_id="light.hallway")


def test_motion_light_suppressed_by_guest_mode() -> None:
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 22:00")
    sim.set_state("input_boolean.guest_mode", "on")
    sim.state_change("binary_sensor.hall_motion", "off", "on")
    sim.assert_not_called("light.turn_on")


# 2. presence away mode -------------------------------------------------------


def test_presence_away_arms_when_both_phones_leave() -> None:
    sim = _sim()
    sim.set_state("device_tracker.john_phone", "not_home")
    sim.state_change("device_tracker.kai_phone", "home", "not_home")
    sim.assert_called("input_boolean.turn_on", entity_id="input_boolean.armed")


def test_presence_away_does_not_arm_when_one_phone_still_home() -> None:
    sim = _sim()
    sim.set_state("device_tracker.john_phone", "home")
    sim.state_change("device_tracker.kai_phone", "home", "not_home")
    sim.assert_not_called("input_boolean.turn_on")


# 3. thermostat schedule ------------------------------------------------------


def test_thermostat_schedule_sets_night_setback() -> None:
    sim = _sim()
    sim.at("2026-07-03 21:59:00")
    sim.advance(minutes=1)
    sim.assert_called("climate.set_temperature", entity_id="climate.living_room", temperature=18)


# 4. actionable notification -----------------------------------------------


def test_notify_with_actions_sends_actionable_notification_on_unlock() -> None:
    # The always-true part of the flow: the front door unlocking sends the
    # actionable notification itself, with both buttons in `data.actions`.
    sim = _sim()
    sim.state_change("lock.front_door", "locked", "unlocked")
    sim.assert_called(
        "notify.mobile_app_kai",
        message="Adjust the upstairs blinds?",
        title="Front Door Unlocked",
        actions=[
            {"action": "OPEN_BLINDS", "title": "Open Blinds", "icon": "mdi:blinds-open"},
            {"action": "CLOSE_BLINDS", "title": "Close Blinds"},
        ],
    )


def test_notify_with_actions_open_blinds_branch_dispatches_on_matching_action() -> None:
    """Full branch dispatch (closing docs/ha-api-notes.md §36.2's
    STOP): tapping the "Open Blinds" notification action fires
    `mobile_app_notification_action` with `action: OPEN_BLINDS`, which must
    resume the recipe's pending `wait_for(event(...))` and run ONLY the
    matching `choose()` branch."""
    sim = _sim()
    sim.state_change("lock.front_door", "locked", "unlocked")
    sim.fire_event("mobile_app_notification_action", action="OPEN_BLINDS")
    sim.assert_called(
        "cover.open_cover",
        entity_id=["cover.bedroom_blinds", "cover.office_blinds"],
    )
    sim.assert_not_called("cover.close_cover")


def test_notify_with_actions_close_blinds_branch_dispatches_on_matching_action() -> None:
    sim = _sim()
    sim.state_change("lock.front_door", "locked", "unlocked")
    sim.fire_event("mobile_app_notification_action", action="CLOSE_BLINDS")
    sim.assert_called(
        "cover.close_cover",
        entity_id=["cover.bedroom_blinds", "cover.office_blinds"],
    )
    sim.assert_not_called("cover.open_cover")


def test_notify_with_actions_non_matching_action_id_takes_no_branch() -> None:
    """A tapped action id that doesn't match either button (e.g. a stale/
    unrelated notification action) resumes the wait but takes neither
    `choose()` branch (no default is defined)."""
    sim = _sim()
    sim.state_change("lock.front_door", "locked", "unlocked")
    sim.fire_event("mobile_app_notification_action", action="SOME_OTHER_ACTION")
    sim.assert_not_called("cover.open_cover")
    sim.assert_not_called("cover.close_cover")


def test_notify_with_actions_timeout_takes_no_branch() -> None:
    """No button tapped within the wait's timeout: the wait times out
    (`continue_on_timeout` defaults true, per `wait_for`'s own default) and
    the sequence continues past it, but since `wait.trigger` is none no
    `choose()` branch's condition can be true."""
    sim = _sim()
    sim.state_change("lock.front_door", "locked", "unlocked")
    sim.advance(minutes=5)
    sim.assert_not_called("cover.open_cover")
    sim.assert_not_called("cover.close_cover")


# 5. washing machine done -----------------------------------------------------


def test_washing_machine_done_fires_on_cross_below_threshold() -> None:
    sim = _sim()
    sim.set_state("sensor.washing_machine_power", "45")
    sim.state_change("sensor.washing_machine_power", "45", "2")
    sim.assert_called("notify.mobile_app_kai", message="Washing machine finished")


def test_washing_machine_done_does_not_fire_while_still_running() -> None:
    sim = _sim()
    sim.set_state("sensor.washing_machine_power", "45")
    sim.state_change("sensor.washing_machine_power", "45", "40")
    sim.assert_not_called("notify.mobile_app_kai")


# 6. guest mode gate -----------------------------------------------------------


def test_guest_mode_gate_notifies_when_not_guest_mode() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.back_door", "closed", "open")
    sim.assert_called("notify.mobile_app_kai", message="Back door opened")


def test_guest_mode_gate_suppressed_in_guest_mode() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "on")
    sim.state_change("binary_sensor.back_door", "closed", "open")
    sim.assert_not_called("notify.mobile_app_kai")


# 7. door left open reminder --------------------------------------------------


def test_door_left_open_reminder_fires_after_holding_10_minutes() -> None:
    sim = _sim()
    sim.state_change("binary_sensor.laundry_door", "closed", "open")
    sim.advance(minutes=10)
    sim.assert_called("notify.mobile_app_kai", message="Laundry door has been open for 10 minutes")


def test_door_left_open_reminder_resets_on_flap() -> None:
    sim = _sim()
    sim.state_change("binary_sensor.laundry_door", "closed", "open")
    sim.advance(minutes=5)
    sim.set_state("binary_sensor.laundry_door", "closed")
    sim.advance(minutes=10)
    sim.assert_not_called("notify.mobile_app_kai")


# 8. good morning shared script ------------------------------------------------


def test_good_morning_script_call_records_the_call_and_runs_the_callee() -> None:
    """A direct `script.<id>` call is recorded as a service call AND expands
    the callee script's sequence inline, blocking, exactly like real HA: the
    call's data becomes the callee's variables, so the
    `param("brightness")` marker renders the caller's 180, not the field
    default."""
    sim = _sim()
    sim.state_change("input_boolean.armed", "on", "off")
    sim.assert_called("script.cookbook_good_morning", brightness=180)
    sim.assert_called("light.turn_on", entity_id="light.bedroom", brightness="180")
    sim.assert_called("light.turn_on", entity_id="light.kitchen", brightness="180")


# 9. vacuum daily schedule -----------------------------------------------------


def test_vacuum_daily_runs_when_armed() -> None:
    sim = _sim()
    sim.set_state("input_boolean.armed", "on")
    sim.at("2026-07-03 09:59:00")
    sim.advance(minutes=1)
    sim.assert_called("vacuum.start", entity_id="vacuum.downstairs")


def test_vacuum_daily_skips_when_not_armed() -> None:
    sim = _sim()
    sim.set_state("input_boolean.armed", "off")
    sim.at("2026-07-03 09:59:00")
    sim.advance(minutes=1)
    sim.assert_not_called("vacuum.start")


# 10. low battery alert (purpose trigger -- fired directly, DESIGN §10.1) -----


def test_low_battery_alert_fires_via_manual_fire() -> None:
    sim = _sim()
    sim.fire("automation:cookbook_low_battery_alert")
    sim.assert_called("notify.mobile_app_kai", message="A sensor's battery is low")


# 11. fan on high temperature ---------------------------------------------------


def test_fan_turns_on_above_threshold() -> None:
    sim = _sim()
    sim.set_state("sensor.outdoor_temperature", "20")
    sim.state_change("sensor.outdoor_temperature", "20", "30")
    sim.assert_called("fan.turn_on", entity_id="fan.bedroom")


# 12. bedtime lights off -------------------------------------------------------


def test_bedtime_lights_off_arms_alarm_when_not_guest_mode() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "off")
    sim.at("2026-07-03 22:59:00")
    sim.advance(minutes=1)
    sim.assert_called(
        "light.turn_off", entity_id=["light.living_room", "light.kitchen", "light.hallway"]
    )
    sim.assert_called("alarm_control_panel.alarm_arm_home", entity_id="alarm_control_panel.home")


def test_bedtime_lights_off_skips_alarm_in_guest_mode() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "on")
    sim.at("2026-07-03 22:59:00")
    sim.advance(minutes=1)
    sim.assert_not_called("alarm_control_panel.alarm_arm_home")
    sim.assert_called(
        "notify.mobile_app_kai",
        message="Bedtime lights off (guest mode: alarm skipped)",
    )


# 13. security check on arm -----------------------------------------------------


def test_security_check_reports_all_secure() -> None:
    sim = _sim()
    sim.set_state("binary_sensor.back_door", "off")
    sim.set_state("lock.front_door", "locked")
    sim.state_change("input_boolean.armed", "off", "on")
    sim.assert_called("notify.mobile_app_kai", message="Armed: all secure")


def test_security_check_silent_when_door_open() -> None:
    sim = _sim()
    sim.set_state("binary_sensor.back_door", "on")
    sim.set_state("lock.front_door", "locked")
    sim.state_change("input_boolean.armed", "off", "on")
    sim.assert_not_called("notify.mobile_app_kai")


# 14. timer-based reminder ------------------------------------------------------


def test_timer_starts_when_washing_machine_turns_on() -> None:
    sim = _sim()
    sim.state_change("switch.washing_machine", "off", "on")
    sim.assert_called("timer.start", entity_id="timer.kitchen", duration="00:45:00")


def test_timer_done_notifies_when_armed() -> None:
    sim = _sim()
    sim.set_state("input_boolean.armed", "on")
    sim.state_change("timer.kitchen", "active", "idle")
    sim.assert_called("notify.mobile_app_kai", message="Kitchen timer finished")


# 15. sunset lights on -----------------------------------------------------------


def test_sunset_turns_on_porch_light() -> None:
    sim = _sim()
    sim.set_sun_times(sunrise="06:00:00", sunset="20:00:00")
    sim.at("2026-07-03 19:59:00")
    sim.advance(minutes=2)
    sim.assert_called("light.turn_on", entity_id="light.porch")


# 16 / 13 combinator coverage is exercised by test 13 above (all_of).

# 17. choose/default fallback is exercised by test 12 above (bedtime_lights_off).

# 18. repeat-flash lights ---------------------------------------------------------


def test_repeat_flash_lights_toggles_three_times() -> None:
    sim = _sim()
    sim.state_change("binary_sensor.front_door", "closed", "open")
    # Each iteration's `delay(seconds=1)` suspends the run -- advance the
    # clock between toggles for the loop to actually complete.
    for _ in range(3):
        sim.advance(seconds=1)
    sim.assert_called("light.toggle", times=3, entity_id="light.hallway")


# 19. wait-then-lock-reminder ------------------------------------------------------


def test_wait_then_lock_reminder_fires_after_timeout() -> None:
    sim = _sim()
    sim.state_change("binary_sensor.front_door", "closed", "open")
    sim.advance(minutes=5)
    sim.assert_called("notify.mobile_app_kai", message="Don't forget to lock the front door")


# 20. purpose-trigger area target (fired directly, DESIGN §10.1) -------------------


def test_purpose_trigger_office_motion_fires_via_manual_fire() -> None:
    sim = _sim()
    sim.fire("automation:cookbook_purpose_trigger_office_motion")
    sim.assert_called("light.turn_on", entity_id="light.office_ceiling")


# 21. guest arrival parallel --------------------------------------------------------


def test_guest_arrival_parallel_runs_all_three_branches() -> None:
    sim = _sim()
    sim.state_change("input_boolean.guest_mode", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.living_room")
    sim.assert_called("light.turn_on", entity_id="light.hallway")
    sim.assert_called("notify.mobile_app_kai", message="Guest mode enabled")


# 22. multi-room motion lights (macro + compile-time loop) -------------------------


def test_multi_room_motion_lights_kitchen() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.kitchen_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.kitchen")
    sim.assert_called("notify.mobile_app_kai", message="Motion detected in the kitchen")
    sim.assert_called("notify.mobile_app_spouse", message="Motion detected in the kitchen")


def test_multi_room_motion_lights_office() -> None:
    sim = _sim()
    sim.set_state("input_boolean.guest_mode", "off")
    sim.state_change("binary_sensor.office_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.office")


# 23. dynamic brightness (template expression) --------------------------------------


def test_dynamic_brightness_dim_when_cold() -> None:
    sim = _sim()
    sim.set_state("sensor.outdoor_temperature", "5")
    sim.state_change("binary_sensor.living_room_motion", "off", "on")
    # The rendered Jinja template comes back as a string (matches HA's own
    # template rendering, which always yields text -- not a Python int).
    sim.assert_called("light.turn_on", entity_id="light.living_room", brightness_pct="30")


def test_dynamic_brightness_bright_when_warm() -> None:
    sim = _sim()
    sim.set_state("sensor.outdoor_temperature", "20")
    sim.state_change("binary_sensor.living_room_motion", "off", "on")
    sim.assert_called("light.turn_on", entity_id="light.living_room", brightness_pct="80")


# 24. stop early if armed -------------------------------------------------------------


def test_stop_if_armed_only_runs_first_action() -> None:
    sim = _sim()
    sim.set_state("input_boolean.armed", "on")
    sim.state_change("binary_sensor.workshop_door", "closed", "open")
    sim.assert_called("light.turn_on", entity_id="light.workshop")
    sim.assert_not_called("notify.mobile_app_kai")


def test_stop_if_armed_runs_both_actions_when_unarmed() -> None:
    sim = _sim()
    sim.set_state("input_boolean.armed", "off")
    sim.state_change("binary_sensor.workshop_door", "closed", "open")
    sim.assert_called("light.turn_on", entity_id="light.workshop")
    sim.assert_called("notify.mobile_app_kai", message="Workshop door opened (unarmed)")
