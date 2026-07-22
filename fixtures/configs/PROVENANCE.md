# Fixture Corpus Provenance

This file documents the source and purpose of each fixture in the corpus. All fixtures are valid Home Assistant JSON configurations extracted from or synthesized to cover the corpus's construct checklist.

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

## Purpose-Specific Triggers and Conditions

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_purpose_trigger_entity_target.json | Shape from https://www.home-assistant.io/triggers/motion.detected/; to be re-verified against a live 2026.7 instance | purpose trigger with entity_id target and for_ duration |
| automation_purpose_trigger_area_behavior_first.json | Shape from https://www.home-assistant.io/triggers/motion.detected/ and https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against a live 2026.7 instance | purpose trigger with area_id target and behavior first |
| automation_purpose_trigger_label_behavior_all.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against a live 2026.7 instance | purpose trigger with label_id target and behavior all |
| automation_purpose_trigger_floor_device.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against a live 2026.7 instance | purpose triggers with floor_id and device_id targets |
| automation_purpose_condition.json | Shape from https://www.home-assistant.io/blog/2026/07/01/release-20267/; to be re-verified against a live 2026.7 instance | purpose-specific condition (climate.is_target_temperature) |
| automation_purpose_trigger_renamed_legacy_key.json | Real-world preserved broken config; battery.low is pre-2026.7 key renamed to battery.became_low without migration; the registry validator flags it with a rename hint; to be re-verified against a live 2026.7 instance | purpose trigger using deprecated/renamed pre-2026.7 key that still stores and deserializes but is no longer valid for new automations |

All fixtures are valid JSON per Home Assistant's schema as of July 2026 and exercise the full construct checklist.

## HA-canonical stored shape (zero-transformation round-trip)

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_ha_canonical_modern.json | Synthesized to match the exact post-2024.10 HA storage shape verified in docs/internals/ha-api-notes.md §10.1 (real POST->GET capture, docs/ha-api-captures/normalize-post-get-pair.json): string `id`, plural `triggers`/`conditions`/`actions`, modern `trigger:`/`action:` discriminators throughout (no `platform:`/`service:` anywhere), no scalar/string-form `delay`, nested `choose`/`default`. This is what a real live `GET /api/config/automation/config/{id}` returns for an automation authored in the current HA UI -- the fixture the decompiler's zero-transformation round-trip (`test_ha_canonical_zero_transformation_roundtrip`) is judged against. | plural schema + modern discriminators + nested choose, all in one already-canonical fixture |

## Real-world smoke-test addendum: mundane UI-authored shapes missed by the synthetic corpus

Source: a live smoke test against a real 2026.7 Home Assistant instance surfaced
118 granular `raw_*` decompiler fallbacks across 101 real objects, tracing to three root causes.
Each is a mundane, extremely common shape the HA UI actually writes that the (hand-authored,
docs-derived) synthetic corpus above never happened to exercise. All three fixtures below are
already in plural/canonical schema (docs/internals/ha-api-notes.md §10.1) with an explicit `id`, mirroring
what `GET /api/config/automation/config/{id}` actually returns.

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_action_metadata_ui_authored.json | Shape observed in a real 2026.7 UI-authored config: every action the HA UI saves is stamped with `"metadata": {}`, observed on all 87 raw actions in the smoke-test sample | actions carrying an empty `metadata: {}` dict alongside `target`+`data`, and a bare-data action with no `target` |
| automation_state_trigger_list_valued_fields.json | Shape observed in a real 2026.7 UI-authored config: the HA UI always stores `entity_id`/`to`/`from` as lists, even for a single entity/value -- a singleton list is never collapsed to a scalar | `state` trigger with singleton-list `entity_id`/`to`/`from`, a second `state` trigger with genuinely multi-entry lists, and both a singleton-list and multi-entry-list `numeric_state` trigger `entity_id` |
| automation_time_trigger_weekday_and_entity_at.json | Shape observed in a real 2026.7 UI-authored config: a weekday-scoped fixed-time trigger (a real schedule-driven wakeup pattern), plus `at` referencing an `input_datetime` entity instead of a literal time string | `time` trigger with `weekday` (list of day abbreviations) alongside `at`, and a second `time` trigger whose `at` is an entity reference (`input_datetime.wakeup`) |

## Residue coverage, round 2: four more UI-authored shapes from a real live bundle

Source: a second live smoke test against a real 2026.7 Home Assistant bundle (101
objects) surfaced 12 more granular `raw_action` fallbacks, tracing to four root causes below --
extending the round-1 pattern (directly above). All four fixtures are in plural/canonical
schema with an explicit `id`, same convention as round 1.

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_action_data_template_ui_authored.json | Shape observed in a real 2026.7 UI-authored config: a service action carries the legacy `data_template` key (HA still stores it verbatim, distinct from `data`) | `climate.set_temperature` action with `target` + `data_template` (a Jinja-templated `temperature` field), no `data` key |
| automation_condition_state_list_valued_fields.json | Shape observed in a real 2026.7 UI-authored config: a state **condition** (not just a trigger, round 1's fix) stores `entity_id`/`state` as lists even for one value | automation-level `state` condition with singleton-list `entity_id`/`state`, plus the same shape nested inside an `if`/`then` action and a `choose` branch's conditions |
| automation_action_step_alias_and_enabled.json | Shape observed in a real 2026.7 UI-authored config: the UI names steps (`alias`) and toggles them (`enabled`) | a plain service call with `alias`, a `delay` with `alias`+`enabled: true`, and a service call with `alias`+`enabled: false` |
| automation_container_recursion_ui_shapes.json | Shape observed in a real 2026.7 UI-authored config: containers (`if`/`else`, `choose`, `parallel`, `wait_for_trigger`) must decompile their inner steps through the same improved path -- a container must never fall back to `raw_action` merely because a child step carries `metadata`/`data_template`, a list-valued state condition, or `alias`/`enabled` | an `if`/`else` action whose `then`/`else` branches carry `metadata`+`alias` and `data_template`+`alias`+`enabled`; a `parallel` whose branches carry an `alias`+`metadata`+`enabled` step and a nested `choose` with a list-valued condition and an `alias`+`metadata` step; a `wait_for_trigger` with a list-valued `state` trigger |

## Residue coverage, round 3 -- final: field measurement 14 -> 7, 5 fixable

Source: field measurement of a real 2026.7 bundle after round 2 landed: `raw_action`
count dropped 14 -> 7. Of the remaining 7, five are fixable (traced to two decompiler root causes
below, one of them a branch-level gap in both `choose` and `parallel`); two are device actions that
stay raw by design (no stable cross-integration schema, same rationale as `device()`
triggers/conditions). All fixtures are in plural/canonical schema with an explicit `id`, same
convention as rounds 1-2.

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_choose_template_condition_branch_alias.json | Shape observed in a real 2026.7 UI-authored config: a `choose` branch carries its own `alias` (naming the branch, not a step inside it) alongside a `template` condition referencing a script variable | `choose` with one branch carrying `alias` + a `template` condition + a `cover.set_cover_position` action with `data` |
| automation_choose_numeric_state_attribute_condition.json | Shape observed in a real 2026.7 UI-authored config: a `choose` branch's `conditions` list carries a `numeric_state` condition with `attribute` -- a regression fixture confirming the nested-in-choose-conditions path resolves through the same `decompile_condition` dispatcher as the top-level path (no code change was needed; this pins the behavior) | `choose` with one branch whose `conditions` is a `numeric_state` condition with `attribute`+`above` |
| automation_parallel_multistep_branch_composite.json | Shape observed in a real 2026.7 UI-authored config: a `parallel` branch running more than one step in its `sequence` (a script call with rich `data`, then a `delay` with all four duration units), alongside a sibling branch containing an `if`/`then` -- the multi-step branch shape (not the delay's `milliseconds` field or the if-block, both of which decompile fine standalone) is what forced the whole `parallel` to `raw_action` | `parallel` with one two-step branch (service call + delay) and one one-step branch (`if`/`then`) |

**Root causes (docs/internals/ha-api-notes.md §21):**
1. A `choose`/`parallel` **branch** carrying its own `alias`/`enabled` was rejected by each handler's
   exact-keys branch-shape check (`set(branch_dict) != {"conditions", "sequence"}` /
   `set(branch_dict) != {"sequence"}`) -- distinct from the round-2 container-level `alias`/`enabled`
   (on the whole `choose()`/`parallel()` block) and from any step's own `alias`/`enabled` inside the
   branch. Fixed by widening both branch-shape checks to tolerate `alias`/`enabled` alongside the
   required keys, and (compiler side) adding `alias=`/`enabled=` to `c.when_(...)` and a new
   `p.branch(alias=, enabled=)` sub-context on `parallel()`'s yielded builder.
2. `_parallel`'s branch handler only accepted a `sequence` of **exactly one** action (matching the
   compiler's original one-action-per-branch auto-derivation) -- a real multi-step branch fell back
   to `raw_action` regardless of what the steps' own content was. Fixed by accepting any-length
   branch sequences; `parallel()` gained a `with p.branch(): ...` sub-context (bound via `as p:`) so
   the compiler can author a multi-step branch, while a bare `with parallel(): action(); action():`
   with no `as` binding is unchanged (each action still becomes its own one-step branch, F3-additive).

## DSL ergonomics round

Source: a bug observed on a real bundle, `scripts/misc.py` -- `repeat.for_each` stored
as a Jinja template STRING (renders to a list at runtime), not a literal list. `repeat_for_each()`'s
`list(items)` silently exploded the template string into a list of individual characters (a `str`
is an `Iterable[str]`) instead of passing it through verbatim; the char-explosion shape survived to
disk because the pull self-check only verified "does the recompiled bundle compile", not "does it
recompile to the same value" (docs/internals/ha-api-notes.md).

| Fixture | Source | Construct |
|---------|--------|-----------|
| automation_repeat_for_each_template_string.json | Bug observed on a real bundle, `scripts/misc.py` | `repeat` with `for_each` stored as a Jinja template string (not a list), proving the compiler passes it through verbatim and the decompiler emits `repeat_for_each("{{ ... }}")` |
