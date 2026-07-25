"""Smoke test -- residue coverage, round 3, final.

Field measurement of a real 2026.7 bundle after round 2 landed: the
``raw_action`` count dropped 14 -> 7. Of the remaining 7, five are fixable
(traced to two decompiler root causes below); two are device actions that stay
raw by design (no stable cross-integration schema, same rationale as
``device()`` triggers/conditions -- not addressed here).

1. A ``choose``/``parallel`` **branch** carrying its own ``alias``/``enabled``
   (naming/toggling that one branch, distinct from the whole container's own
   ``alias``/``enabled`` and from any step's own ``alias``/``enabled`` inside
   the branch) was rejected by each handler's exact-keys branch-shape check.
2. ``_parallel``'s branch handler only accepted a ``sequence`` of exactly one
   action (matching the compiler's original one-action-per-branch shape) -- a
   real multi-step branch (a script call with rich ``data``, then a ``delay``
   with all four duration units) fell back to ``raw_action`` regardless of the
   steps' own content, which decompile fine standalone.

Each gap gets a builder-level unit test (this file) plus a new corpus fixture
under ``fixtures/configs/`` that the existing parametrized round-trip
(``test_roundtrip_corpus.py``) and coverage (``test_decompile_coverage.py``)
tests pick up automatically. A regression fixture
(``automation_choose_numeric_state_attribute_condition.json``) pins that a
``numeric_state`` condition with ``attribute`` nested inside ``choose``
``conditions`` already resolves through the same ``decompile_condition``
dispatcher as the top-level path -- no code change needed there, verified here
so it never silently regresses.
"""

from __future__ import annotations

from hassle.compiler.actions import delay, service
from hassle.compiler.control_flow import choose, parallel
from hassle.compiler.recording import recording
from hassle.compiler.templates import template
from hassle.decompiler.actions import decompile_action
from hassle.decompiler.exprs import decompile_condition

# ---------------------------------------------------------------------------
# Gap 1a -- `choose` branch-level `alias`/`enabled`.
# ---------------------------------------------------------------------------


def test_choose_when_accepts_branch_alias_and_enabled_kwargs() -> None:
    with (
        recording() as rec,
        choose() as c,
        c.when_(template("{{ 1 == 1 }}"), alias="Cover open or opening", enabled=False),
    ):
        service("cover.set_cover_position", target={"entity_id": "cover.garage"}, position=50)
    (action,) = rec.actions
    (branch,) = action.body["choose"]
    assert branch["alias"] == "Cover open or opening"
    assert branch["enabled"] is False
    assert branch["conditions"] == [{"condition": "template", "value_template": "{{ 1 == 1 }}"}]


def test_decompile_choose_branch_with_alias_round_trips_to_when_kwarg() -> None:
    body = {
        "choose": [
            {
                "alias": "Cover open or opening",
                "conditions": [
                    {
                        "condition": "template",
                        "value_template": "{{ position == 'open' or position == 'opening' }}",
                    }
                ],
                "sequence": [
                    {
                        "action": "cover.set_cover_position",
                        "target": {"entity_id": "cover.garage"},
                        "data": {"position": 50},
                    }
                ],
            }
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "with choose() as c:" in src
    assert "alias='Cover open or opening'" in src
    assert "with c.when_(" in src


def test_decompile_choose_branch_with_enabled_false() -> None:
    body = {
        "choose": [
            {
                "enabled": False,
                "conditions": [{"condition": "template", "value_template": "{{ 1 }}"}],
                "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}],
            }
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "enabled=False" in src


# ---------------------------------------------------------------------------
# Gap 1b -- `parallel` branch-level `alias`/`enabled` (via `p.branch(...)`).
# ---------------------------------------------------------------------------


def test_parallel_yields_builder_with_branch_context_manager() -> None:
    with recording() as rec, parallel() as p:
        service("light.turn_on", target={"entity_id": "light.a"})
        with p.branch(alias="Notify branch", enabled=True):
            service("script.notify_all", title="t")
    (action,) = rec.actions
    branches = action.body["parallel"]
    assert len(branches) == 2
    assert branches[0] == {
        "sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.a"}}]
    }
    assert branches[1]["alias"] == "Notify branch"
    assert branches[1]["enabled"] is True
    assert branches[1]["sequence"] == [{"action": "script.notify_all", "data": {"title": "t"}}]


def test_bare_parallel_with_no_as_binding_still_works_unchanged() -> None:
    with recording() as rec, parallel():
        service("light.turn_on", target={"entity_id": "light.a"})
        service("light.turn_on", target={"entity_id": "light.b"})
    (action,) = rec.actions
    assert action.body["parallel"] == [
        {"sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.a"}}]},
        {"sequence": [{"action": "light.turn_on", "target": {"entity_id": "light.b"}}]},
    ]


def test_decompile_parallel_branch_with_alias_uses_p_branch() -> None:
    body = {
        "parallel": [
            {
                "alias": "Notify branch",
                "sequence": [{"action": "script.notify_all", "data": {"title": "t"}}],
            }
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "with parallel() as p:" in src
    assert "with p.branch(alias='Notify branch'):" in src


# ---------------------------------------------------------------------------
# Gap 2 -- `parallel` branch with more than one step in its `sequence`.
# ---------------------------------------------------------------------------


def test_parallel_branch_context_manager_records_multiple_steps() -> None:
    with recording() as rec, parallel() as p, p.branch():
        service("script.notify_all", title="Garage", message="Door opened")
        delay(hours=0, minutes=1, seconds=30, milliseconds=500)
    (action,) = rec.actions
    (branch,) = action.body["parallel"]
    assert branch["sequence"] == [
        {"action": "script.notify_all", "data": {"title": "Garage", "message": "Door opened"}},
        {"delay": {"hours": 0, "minutes": 1, "seconds": 30, "milliseconds": 500}},
    ]


def test_decompile_parallel_multistep_branch_composite() -> None:
    body = {
        "parallel": [
            {
                "sequence": [
                    {
                        "action": "script.notify_all",
                        "data": {
                            "title": "Garage",
                            "message": "Door opened",
                            "tag": "garage_door",
                            "action_button": "view",
                            "action_button_icon": "mdi:garage-open",
                        },
                    },
                    {"delay": {"hours": 0, "minutes": 1, "seconds": 30, "milliseconds": 500}},
                ]
            },
            {
                "sequence": [
                    {
                        "if": [
                            {
                                "condition": "state",
                                "entity_id": ["cover.garage"],
                                "state": ["open"],
                            }
                        ],
                        "then": [
                            {"action": "light.turn_on", "target": {"entity_id": "light.garage"}}
                        ],
                    }
                ]
            },
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "with parallel() as p:" in src
    assert "with p.branch():" in src
    assert "delay(hours=0, minutes=1, seconds=30, milliseconds=500)" in src
    assert "with if_then(" in src


# ---------------------------------------------------------------------------
# Gap 3 (verification, no fix needed) -- numeric_state condition w/ attribute
# nested inside choose `conditions` uses the same dispatcher as top-level.
# ---------------------------------------------------------------------------


def test_numeric_state_condition_with_attribute_top_level() -> None:
    body = {
        "condition": "numeric_state",
        "entity_id": "cover.garage",
        "attribute": "current_position",
        "above": 0,
    }
    src = decompile_condition(body)
    assert src == "numeric_state(e.cover.garage, attribute='current_position', above=0)"


def test_decompile_choose_branch_numeric_state_attribute_condition() -> None:
    body = {
        "choose": [
            {
                "conditions": [
                    {
                        "condition": "numeric_state",
                        "entity_id": "cover.garage",
                        "attribute": "current_position",
                        "above": 0,
                    }
                ],
                "sequence": [
                    {"action": "cover.stop_cover", "target": {"entity_id": "cover.garage"}}
                ],
            }
        ]
    }
    src = "\n".join(decompile_action(body))
    assert "raw_action" not in src
    assert "numeric_state(e.cover.garage, attribute='current_position', above=0)" in src


def test_choose_branch_with_empty_conditions_round_trips() -> None:
    # Owner bundle, the last straggler: the UI expresses an unconditional
    # final branch as `"conditions": []` (distinct from `default:` -- must be
    # preserved exactly, not converted). when_() with zero conditions compiles
    # to conditions: []; the decompiler emits `c.when_()` for it.
    from hassle.decompiler.actions import decompile_action

    block = {
        "choose": [
            {
                "conditions": [
                    {"condition": "state", "entity_id": "input_boolean.x", "state": "on"}
                ],
                "sequence": [{"action": "light.turn_on", "metadata": {}, "data": {}}],
            },
            {"conditions": [], "sequence": [{"stop": "Fully Closed"}]},
        ]
    }
    src = decompile_action(block)
    joined = "\n".join(src)
    assert "raw_action" not in joined, joined
    assert "when_()" in joined, joined
