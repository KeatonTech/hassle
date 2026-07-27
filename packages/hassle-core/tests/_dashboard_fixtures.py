"""Shared dashboard envelope fixtures for the DB1 IR tests.

One realistic non-default envelope and one default-dashboard envelope, both
shaped exactly as docs/internals/dashboards-design.md §3.2 specifies:
``{"meta": <registry item minus id/mode> | null, "config": <view config verbatim>}``.

The realistic envelope deliberately plants, at every level, the shapes that
have historically been corrupted by generic transforms:

- ``tap_action``/``hold_action``/``double_tap_action`` payloads carrying the
  **legacy ``service:`` key** (§2.2 item 5) — the §3.3 bug class;
- a ``custom:`` third-party card (D-G5: round-trips raw, never guessed);
- invented/unknown keys at the envelope top level, in ``meta``, in the view,
  in a section, and deep inside a nested card;
- a bare ``{"delay": ...}`` mapping inside a third-party card body, which the
  generic ``modernize_for_comparison`` delay rewrite would otherwise rewrite.
"""

from __future__ import annotations

from typing import Any

# A realistic storage-mode dashboard: sections view + masonry view, badges,
# nested stacks, a conditional card, a custom card, unknown keys everywhere.
DASHBOARD_ENVELOPE: dict[str, Any] = {
    "meta": {
        "url_path": "climate-control",
        "title": "Climate",
        "icon": "mdi:thermostat",
        "show_in_sidebar": True,
        "require_admin": False,
        "invented_meta_key": {"kept": [1, 2, 3]},
    },
    "config": {
        "views": [
            {
                "title": "Overview",
                "path": "overview",
                "type": "sections",
                "max_columns": 3,
                "invented_view_key": {"deep": {"deeper": "kept"}},
                "badges": [
                    {"type": "entity", "entity": "sensor.outside_temp"},
                    "sensor.legacy_bare_badge",
                ],
                "sections": [
                    {
                        "type": "grid",
                        "column_span": 2,
                        "invented_section_key": ["kept", {"still": "here"}],
                        "cards": [
                            {"type": "heading", "heading": "Heat pumps"},
                            {
                                "type": "tile",
                                "entity": "climate.living_room",
                                # The §3.3 bug class: a LEGACY call-service
                                # action payload. `service:` here is a card
                                # option, not an automation action.
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "climate.set_preset_mode",
                                    "data": {"preset_mode": "comfort"},
                                    "target": {"entity_id": "climate.living_room"},
                                },
                                "hold_action": {
                                    "action": "call-service",
                                    "service": "climate.turn_off",
                                },
                                "double_tap_action": {"action": "more-info"},
                                "features": [{"type": "climate-hvac-modes"}],
                                "invented_card_key": {"deepest": 3.14},
                            },
                            {
                                "type": "vertical-stack",
                                "cards": [
                                    {
                                        "type": "button",
                                        "entity": "script.movie_time",
                                        # The MODERN spelling must survive
                                        # untouched too.
                                        "tap_action": {
                                            "action": "perform-action",
                                            "perform_action": "script.movie_time",
                                        },
                                    },
                                    {
                                        "type": "conditional",
                                        "conditions": [
                                            {
                                                "condition": "state",
                                                "entity": "input_boolean.guest_mode",
                                                "state": "on",
                                            }
                                        ],
                                        "card": {
                                            "type": "custom:bubble-card",
                                            "card_type": "button",
                                            # A bare {"delay": ...} mapping
                                            # inside a third-party card body:
                                            # the generic modernize delay
                                            # rewrite must not touch it.
                                            "hold_sequence": [{"delay": "00:00:30"}],
                                            "tap_action": {
                                                "action": "call-service",
                                                "service": "light.toggle",
                                            },
                                            "unknown_custom_key": {"a": [None, True, "z"]},
                                        },
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
            {
                # Legacy masonry view: NO `type` key at all (§2.2 item 4).
                "title": "Legacy",
                "path": "legacy",
                "cards": [
                    {
                        "type": "entities",
                        "title": "All heads",
                        "entities": [
                            "climate.living_room",
                            {"type": "divider"},
                            {
                                "entity": "climate.office",
                                "tap_action": {
                                    "action": "call-service",
                                    "service": "climate.set_temperature",
                                },
                            },
                        ],
                    }
                ],
            },
        ],
        "invented_config_key": "kept",
    },
    "invented_envelope_key": {"top": "level"},
}

# The default dashboard: no registry item at all, so `meta` is explicitly null
# (§3.2). It must round-trip WITH the null — `meta` was set, so
# `exclude_unset=True` still emits it.
DEFAULT_DASHBOARD_ENVELOPE: dict[str, Any] = {
    "meta": None,
    "config": {
        "views": [
            {
                "title": "Home",
                "type": "sections",
                "sections": [
                    {
                        "type": "grid",
                        "cards": [
                            {
                                "type": "light",
                                "entity": "light.hall",
                                "hold_action": {
                                    "action": "call-service",
                                    "service": "light.turn_off",
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    },
}
