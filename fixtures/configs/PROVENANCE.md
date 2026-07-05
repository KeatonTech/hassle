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
| automation_math_shade_sun.json | https://www.home-assistant.io/docs/configuration/templating/ (math section) + https://www.home-assistant.io/integrations/sun/ | time_pattern trigger with math template (cos) in service call |
| automation_math_variables_chain.json | https://www.home-assistant.io/docs/configuration/templating/ (math section) | variables with nested template evaluation (sin) consumed by later templates |
| automation_math_template_trigger.json | https://www.home-assistant.io/docs/configuration/templating/ (math section) | template trigger using math functions (atan2, sqrt) |

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
- **Action constructs:** choose, if/then/else_then, repeat (count/while/until/for_each), parallel, wait_template, wait_for_trigger, stop, variables (with nested template chains), delay (numeric and hh:mm:ss), service call (longhand and shorthand)
- **Math functions in templates:** cos, sin, atan2, sqrt, pi constant (in triggers, conditions, and action data)
- **Modes:** single, restart, queued, parallel (all 4)
- **Blueprints:** use_blueprint with inputs
- **Helpers:** input_boolean, input_number, input_select, input_text, input_datetime, input_button, counter, timer, schedule (all 9 storage-collection types)
- **Scripts:** basic, fields/parameters, mode: queued
- **Real-world:** legacy platform key naming, mixed key order preservation, trigger_id + trigger_variables

## Purpose-Specific Triggers and Conditions (M0.1 addendum)

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_purpose_trigger_entity_target.json | Shape from https://www.home-assistant.io/triggers/motion.detected/; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose trigger with entity_id target and for_ duration |
| automation_purpose_trigger_area_behavior_first.json | Shape from https://www.home-assistant.io/triggers/motion.detected/ and https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose trigger with area_id target and behavior first |
| automation_purpose_trigger_label_behavior_all.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose trigger with label_id target and behavior all |
| automation_purpose_trigger_floor_device.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose triggers with floor_id and device_id targets |
| automation_purpose_condition.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose-specific condition (climate.is_target_temperature) |
| automation_purpose_trigger_renamed_legacy_key.json | Real-world preserved broken config; battery.low is pre-2026.7 key renamed to battery.became_low without migration; M3 will flag with rename hint; to be re-verified against live 2026.7 in M6 (MILESTONES M6 test 8) | purpose trigger using deprecated/renamed pre-2026.7 key that still stores and deserializes but is no longer valid for new automations |

All fixtures are valid JSON per Home Assistant's schema as of July 2026 and exercise the full M0 construct checklist.

## M2 addendum: HA-canonical stored shape (zero-transformation round-trip)

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_ha_canonical_modern.json | Synthesized to match the exact post-2024.10 HA storage shape verified in docs/ha-api-notes.md §10.1 (real POST->GET capture, docs/ha-api-captures/normalize-post-get-pair.json): string `id`, plural `triggers`/`conditions`/`actions`, modern `trigger:`/`action:` discriminators throughout (no `platform:`/`service:` anywhere), no scalar/string-form `delay`, nested `choose`/`default`. This is what a real live `GET /api/config/automation/config/{id}` returns for an automation authored in the current HA UI -- the fixture the decompiler's zero-transformation round-trip (`test_ha_canonical_zero_transformation_roundtrip`) is judged against. | plural schema + modern discriminators + nested choose, all in one already-canonical fixture |

## Real-world smoke-test addendum (task #5): mundane UI-authored shapes missed by the synthetic corpus

Source: the owner's first live smoke test against a real 2026.7 Home Assistant instance surfaced
118 granular `raw_*` decompiler fallbacks across 101 real objects, tracing to three root causes.
Each is a mundane, extremely common shape the HA UI actually writes that the (hand-authored,
docs-derived) synthetic corpus above never happened to exercise. All three fixtures below are
already in plural/canonical schema (docs/ha-api-notes.md §10.1) with an explicit `id`, mirroring
what `GET /api/config/automation/config/{id}` actually returns.

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_action_metadata_ui_authored.json | Shape observed in a real 2026.7 UI-authored config: every action the HA UI saves is stamped with `"metadata": {}`, observed on all 87 raw actions in the smoke-test sample | actions carrying an empty `metadata: {}` dict alongside `target`+`data`, and a bare-data action with no `target` |
| automation_state_trigger_list_valued_fields.json | Shape observed in a real 2026.7 UI-authored config: the HA UI always stores `entity_id`/`to`/`from` as lists, even for a single entity/value -- a singleton list is never collapsed to a scalar | `state` trigger with singleton-list `entity_id`/`to`/`from`, a second `state` trigger with genuinely multi-entry lists, and both a singleton-list and multi-entry-list `numeric_state` trigger `entity_id` |
| automation_time_trigger_weekday_and_entity_at.json | Shape observed in a real 2026.7 UI-authored config: a weekday-scoped fixed-time trigger (the owner's schedule-driven wakeups), plus `at` referencing an `input_datetime` entity instead of a literal time string | `time` trigger with `weekday` (list of day abbreviations) alongside `at`, and a second `time` trigger whose `at` is an entity reference (`input_datetime.wakeup`) |
