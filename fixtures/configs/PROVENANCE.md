# Fixture Corpus Provenance

This file documents the source and purpose of each fixture in the corpus. All fixtures are valid Home Assistant JSON configurations extracted from or synthesized to cover the M0 milestone construct checklist.

## Trigger Automations

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_state_trigger_basic.json | HA docs, basic example | state trigger with to filter |
| automation_numeric_state_trigger.json | HA docs, climate example | numeric_state trigger with above |
| automation_time_trigger.json | HA docs, time example | time trigger at specific time |
| automation_time_pattern_trigger.json | HA docs, pattern example | time_pattern trigger |
| automation_sun_trigger.json | HA docs, sun example | sun trigger with after |
| automation_event_trigger.json | HA docs, event example | event trigger with event_type |
| automation_zone_trigger.json | HA docs, zone example | zone trigger with entity_id/zone/event |
| automation_template_trigger.json | HA docs, template example | template trigger with value_template |
| automation_webhook_trigger.json | HA docs, webhook example | webhook trigger with webhook_id |
| automation_device_trigger.json | HA docs, device example | device trigger with type/subtype |
| automation_mqtt_trigger.json | HA docs, mqtt example | mqtt trigger with topic/payload |
| automation_calendar_trigger.json | HA docs, calendar example | calendar trigger with event |
| automation_persistent_notification_trigger.json | HA docs, notification example | persistent_notification trigger |
| automation_geo_location_trigger.json | HA docs, geo_location example | geo_location trigger |
| automation_homeassistant_start_trigger.json | HA docs, system example | homeassistant start event |
| automation_homeassistant_shutdown_trigger.json | HA docs, system example | homeassistant shutdown event |
| automation_tag_trigger.json | HA docs, nfc tag example | tag trigger with tag_id |

## Action/Condition Construct Automations

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_choose_action.json | HA docs, choose example | choose with multiple branches and default |
| automation_if_then_else.json | HA docs, if/then example | if/then/else_then branching |
| automation_repeat_count.json | HA docs, repeat example | repeat with count |
| automation_repeat_while.json | HA docs, repeat example | repeat with while condition |
| automation_repeat_until.json | HA docs, repeat example | repeat with until condition |
| automation_repeat_for_each.json | HA docs, repeat example | repeat with for_each |
| automation_parallel_action.json | HA docs, parallel example | parallel action with multiple sequences |
| automation_wait_template.json | HA docs, wait example | wait_template action |
| automation_wait_for_trigger.json | HA docs, wait example | wait_for_trigger action |
| automation_stop_action.json | HA docs, stop example | stop action in if/then |
| automation_variables_action.json | HA docs, variables example | variables in action sequence |
| automation_delay_numeric.json | HA docs, delay example | delay with numeric seconds |
| automation_delay_hh_mm_ss.json | HA docs, delay example | delay with hh:mm:ss format |
| automation_service_call_longhand.json | HA docs, service example | service call with full data structure |
| automation_condition_state.json | HA docs, condition example | automation-level state condition |

## Condition Type Automations

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_condition_numeric_state.json | HA docs, numeric condition example | numeric_state condition |
| automation_condition_time.json | HA docs, time condition example | time condition with weekday |
| automation_condition_sun.json | HA docs, sun condition example | sun condition with offset |
| automation_condition_zone.json | HA docs, zone condition example | zone condition |
| automation_condition_template.json | HA docs, template condition example | template condition |
| automation_condition_device.json | HA docs, device condition example | device condition with type |
| automation_condition_and_or_not.json | HA docs, condition logic example | and/or/not condition composition |
| automation_condition_trigger.json | HA docs, trigger condition example | trigger condition checking trigger_id |
| automation_mixed_triggers_conditions.json | Real-world synthesis | multiple triggers + complex conditions |

## Mode Automations

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_mode_single.json | HA docs, mode example | mode: single (ignores re-trigger) |
| automation_mode_restart.json | HA docs, mode example | mode: restart with max_exceeded |
| automation_mode_queued.json | HA docs, mode example | mode: queued with max |
| automation_mode_parallel_with_max.json | HA docs, mode example | mode: parallel with max and max_exceeded |

## Blueprint and Real-World Automations

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_blueprint_based.json | HA docs, blueprint example | use_blueprint with inputs |
| automation_legacy_platform_naming.json | Real-world legacy HA export | uses platform: key (legacy format) |
| automation_mixed_key_order.json | Real-world HA export | preserves messy key ordering |
| automation_with_trigger_id_and_variables.json | HA docs, advanced example | trigger_id and trigger_variables |

## Script Fixtures

| Fixture | Source | Construct |
|---------|--------|-----------|
| script_basic.json | HA docs, script example | basic script with sequence |
| script_with_fields.json | HA docs, script example | script with fields for parameters |
| script_mode_queued.json | HA docs, script example | script with mode: queued |

## Helper Fixtures

| Fixture | Source | Construct |
|---------|--------|-----------|
| helper_input_boolean.json | HA storage collection schema | input_boolean helper |
| helper_input_number.json | HA storage collection schema | input_number with slider mode |
| helper_input_select.json | HA storage collection schema | input_select with options |
| helper_input_text.json | HA storage collection schema | input_text with pattern |
| helper_input_datetime.json | HA storage collection schema | input_datetime with date+time |
| helper_input_button.json | HA storage collection schema | input_button with device_class |
| helper_counter.json | HA storage collection schema | counter with initial/min/max |
| helper_timer.json | HA storage collection schema | timer with duration |
| helper_schedule.json | HA storage collection schema | schedule helper |

## Coverage Summary

- **Trigger types:** state, numeric_state, time, time_pattern, sun, event, zone, template, webhook, device, mqtt, calendar, persistent_notification, geo_location, homeassistant (start/shutdown), tag (17 types)
- **Condition types:** state, numeric_state, time, sun, zone, template, device, and (2), or (2), not (1), trigger (all 8 types)
- **Action constructs:** choose, if/then/else_then, repeat (count/while/until/for_each), parallel, wait_template, wait_for_trigger, stop, variables, delay (numeric and hh:mm:ss), service call (longhand and shorthand)
- **Modes:** single, restart, queued, parallel (all 4)
- **Blueprints:** use_blueprint with inputs
- **Helpers:** input_boolean, input_number, input_select, input_text, input_datetime, input_button, counter, timer, schedule (all 9 storage-collection types)
- **Scripts:** basic, fields/parameters, mode: queued
- **Real-world:** legacy platform key naming, mixed key order preservation, trigger_id + trigger_variables

All fixtures are valid JSON per Home Assistant's schema as of July 2026 and exercise the full M0 construct checklist.
