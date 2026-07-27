"""Dashboards are EXEMPT from every HA-shape rewrite the IR applies to
automations and scripts (docs/internals/dashboards-design.md §3.3).

This is a known bug class, written test-first (R4 applied pre-emptively).

`normalize_ha`'s generic branch recursively rewrites `service:` -> `action:`
inside action containers, reproducing HA's 2024.10+ storage normalization for
automations/scripts. A Lovelace card body legitimately contains `service:` keys
of its own — inside `tap_action`/`hold_action`/`double_tap_action` payloads
using the legacy `call-service` form (§2.2 item 5), which HA stores VERBATIM
(the Lovelace store performs no schema validation and no normalization at all).

Rewriting one would silently change a user's dashboard: the card would stop
calling the service, and the drifted hash would show up as a phantom conflict
on every subsequent plan. So `normalize_ha` must be an exact identity function
for `kind == "dashboard"`, `storage_canonical` must have no entries for the
kind, and `modernize_for_comparison` must leave dashboard bodies alone.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from hassle.ir.canonical import canonical_json, storage_canonical
from hassle.ir.modernize import modernize_for_comparison
from hassle.ir.normalize import normalize_ha

from _dashboard_fixtures import DASHBOARD_ENVELOPE, DEFAULT_DASHBOARD_ENVELOPE

# The minimal reproduction, kept separate from the big fixture so the failure
# message points straight at the bug.
TAP_ACTION_ENVELOPE: dict[str, Any] = {
    "meta": {"url_path": "climate-control", "title": "Climate"},
    "config": {
        "views": [
            {
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "tile",
                                "entity": "climate.living_room",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "climate.set_preset_mode",
                                    "data": {"preset_mode": "comfort"},
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    },
}


# -- normalize_ha: identity for the kind (§3.3) ----------------------------


def test_normalize_ha_is_identity_for_a_dashboard_tap_action_service() -> None:
    """THE regression test: `service:` inside a card's `tap_action` is a card
    option, not an automation action, and must survive verbatim."""
    out = normalize_ha(TAP_ACTION_ENVELOPE, kind="dashboard")
    assert out == TAP_ACTION_ENVELOPE
    assert canonical_json(out) == canonical_json(TAP_ACTION_ENVELOPE)

    tap = out["config"]["views"][0]["sections"][0]["cards"][0]["tap_action"]
    assert "service" in tap, "the legacy call-service key was rewritten away"
    assert tap["service"] == "climate.set_preset_mode"
    assert tap["action"] == "call-service"


def test_normalize_ha_is_identity_for_the_full_dashboard_envelope() -> None:
    out = normalize_ha(DASHBOARD_ENVELOPE, kind="dashboard")
    assert canonical_json(out) == canonical_json(DASHBOARD_ENVELOPE)


def test_normalize_ha_is_identity_for_the_default_dashboard_envelope() -> None:
    out = normalize_ha(DEFAULT_DASHBOARD_ENVELOPE, kind="dashboard")
    assert canonical_json(out) == canonical_json(DEFAULT_DASHBOARD_ENVELOPE)


def test_normalize_ha_does_not_rewrite_dashboard_action_shaped_keys() -> None:
    """The generic branch recurses into `actions`/`sequence`/`then`/`else`/
    `default` keys. A card body may carry any of those names (`default` is a
    real option on several built-in cards); none may be touched."""
    envelope: dict[str, Any] = {
        "meta": {"url_path": "trap-dashboard"},
        "config": {
            "views": [
                {
                    "cards": [
                        {
                            "type": "custom:some-card",
                            "actions": [{"service": "light.toggle"}],
                            "sequence": [{"service": "script.turn_on"}],
                            "default": {"service": "scene.turn_on"},
                            "then": [{"service": "a.b"}],
                            "else": [{"service": "c.d"}],
                        }
                    ]
                }
            ]
        },
    }
    assert normalize_ha(envelope, kind="dashboard") == envelope


def test_normalize_ha_does_not_pluralize_dashboard_outer_keys() -> None:
    """The outer singular->plural rename is `kind == "automation"`-only
    already, but a dashboard body carrying literal `trigger`/`condition`/
    `action` top-level keys (a third-party strategy config may) must stay put
    regardless."""
    envelope: dict[str, Any] = {
        "meta": None,
        "config": {"strategy": {"type": "custom:x", "trigger": 1, "action": 2, "condition": 3}},
    }
    assert normalize_ha(envelope, kind="dashboard") == envelope


def test_normalize_ha_is_identity_for_top_level_action_shaped_keys() -> None:
    """The guard must be STRUCTURAL, not incidental.

    `normalize_ha`'s generic branch only recurses into a body's TOP-LEVEL
    `actions`/`sequence` keys, so a well-formed `{"meta", "config"}` envelope
    happens to survive it untouched even without a kind guard. That accident is
    not a contract: `IRObject` is `extra="allow"`, a `@raw_dashboard` body may
    carry any top-level key at all, and a future widening of the generic
    recursion would silently start rewriting card bodies again.

    So the contract is stated at the kind level -- for `kind == "dashboard"`,
    `normalize_ha` rewrites NOTHING, whatever the body's shape.
    """
    envelope: dict[str, Any] = {
        "meta": {"url_path": "raw-one"},
        "config": {"views": []},
        "actions": [{"service": "light.turn_on"}],
        "sequence": [{"service": "script.turn_on"}],
    }
    assert normalize_ha(envelope, kind="dashboard") == envelope


def test_normalize_ha_returns_a_copy_not_the_input_object() -> None:
    """Identity of VALUE, not of object: the frozen `normalize_ha` contract is
    "never mutates its input", and callers rely on being able to mutate the
    result. An identity fast-path must not hand back the caller's own dict."""
    out = normalize_ha(TAP_ACTION_ENVELOPE, kind="dashboard")
    assert out is not TAP_ACTION_ENVELOPE
    before = json.dumps(TAP_ACTION_ENVELOPE, sort_keys=True)
    out["config"]["views"][0]["sections"][0]["cards"].append({"type": "markdown"})
    out["meta"]["title"] = "mutated"
    assert json.dumps(TAP_ACTION_ENVELOPE, sort_keys=True) == before


def test_normalize_ha_is_idempotent_for_dashboards() -> None:
    once = normalize_ha(DASHBOARD_ENVELOPE, kind="dashboard")
    twice = normalize_ha(once, kind="dashboard")
    assert canonical_json(twice) == canonical_json(DASHBOARD_ENVELOPE)


def test_normalize_ha_still_rewrites_service_for_automations() -> None:
    """The exemption is scoped to the kind — the automation behavior this
    guard sits next to must be untouched."""
    automation: dict[str, Any] = {
        "id": "a1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x"}],
        "action": [{"service": "light.turn_on"}],
    }
    out = normalize_ha(automation, kind="automation")
    assert out["actions"] == [{"action": "light.turn_on"}]


# -- storage_canonical: no entries for the kind (§3.3) ---------------------


def test_storage_canonical_is_identity_for_dashboards() -> None:
    """The Lovelace store saves the config body verbatim — no server-side
    schema validation, no materialized defaults (§2.2 item 2). If DB0 finds
    otherwise, the findings go in `_STORAGE_DEFAULTS`/`_STORAGE_FLOAT_FIELDS`
    and this test changes with them."""
    out = storage_canonical("dashboard", DASHBOARD_ENVELOPE)
    assert out == DASHBOARD_ENVELOPE
    assert canonical_json(out) == canonical_json(DASHBOARD_ENVELOPE)
    assert storage_canonical("dashboard", DEFAULT_DASHBOARD_ENVELOPE) == DEFAULT_DASHBOARD_ENVELOPE


# -- modernize_for_comparison: dashboards pass through uncorrupted --------


def test_modernize_for_comparison_leaves_dashboard_envelopes_alone() -> None:
    out = modernize_for_comparison(DASHBOARD_ENVELOPE, kind="dashboard")
    assert canonical_json(out) == canonical_json(DASHBOARD_ENVELOPE)
    assert canonical_json(
        modernize_for_comparison(DEFAULT_DASHBOARD_ENVELOPE, kind="dashboard")
    ) == canonical_json(DEFAULT_DASHBOARD_ENVELOPE)


def test_modernize_for_comparison_does_not_rewrite_a_delay_inside_a_card() -> None:
    """`_modernize_delay` walks EVERY dict in the body and rewrites any
    `{"delay": <str|num>}` singleton mapping. A third-party card body may
    contain exactly that shape; a dashboard is not an automation, and the
    decompiler applies no such modernization to card bodies, so rewriting it
    would make a faithful round-trip compare as drifted forever."""
    envelope: dict[str, Any] = {
        "meta": {"url_path": "delay-card"},
        "config": {
            "views": [
                {
                    "cards": [
                        {
                            "type": "custom:sequence-card",
                            "steps": [{"delay": "00:00:30"}, {"delay": 5}],
                        }
                    ]
                }
            ]
        },
    }
    assert modernize_for_comparison(envelope, kind="dashboard") == envelope


def test_modernize_for_comparison_does_not_rewrite_platform_inside_a_card() -> None:
    """`_modernize_wait_for_trigger` rewrites inner `platform:` -> `trigger:`
    under any nested `wait_for_trigger` key, wherever it appears."""
    envelope: dict[str, Any] = {
        "meta": {"url_path": "trigger-card"},
        "config": {
            "views": [
                {
                    "cards": [
                        {
                            "type": "custom:script-card",
                            "wait_for_trigger": [{"platform": "state", "entity_id": "light.a"}],
                        }
                    ]
                }
            ]
        },
    }
    assert modernize_for_comparison(envelope, kind="dashboard") == envelope


def test_modernize_for_comparison_never_mutates_a_dashboard_input() -> None:
    original = copy.deepcopy(DASHBOARD_ENVELOPE)
    out = modernize_for_comparison(DASHBOARD_ENVELOPE, kind="dashboard")
    assert out is not DASHBOARD_ENVELOPE
    assert DASHBOARD_ENVELOPE == original


def test_modernize_for_comparison_still_modernizes_automations() -> None:
    automation: dict[str, Any] = {
        "id": "a1",
        "trigger": [{"platform": "state", "entity_id": "binary_sensor.x"}],
        "action": [{"delay": "00:01:00"}],
    }
    out = modernize_for_comparison(automation, kind="automation")
    assert out["triggers"] == [{"trigger": "state", "entity_id": "binary_sensor.x"}]
    assert out["actions"] == [{"delay": {"minutes": 1}}]
