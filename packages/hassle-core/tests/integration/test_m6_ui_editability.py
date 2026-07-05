"""MILESTONES M6 test 6 — UI-editability check (I2 proxy).

After apply, the automation's config is fetchable via the config API and the
automation entity exists in the entity registry with `unique_id == config id`
(docs/ha-api-notes.md §2: `unique_id == config id` is the I2 anchor — the same
identity the UI edits through). This proves the object Hassle wrote is one the
UI can edit, without driving a browser.
"""

from __future__ import annotations

from hassle.backend import DirectBackend


def test_applied_automation_is_ui_editable(ha: DirectBackend) -> None:
    ha.create(
        "automation",
        {
            "id": "ui_editable",
            "alias": "UI Editable Automation",
            "trigger": [{"platform": "state", "entity_id": "input_boolean.x", "to": "on"}],
            "condition": [],
            "action": [
                {"service": "input_boolean.toggle", "target": {"entity_id": "input_boolean.x"}}
            ],
        },
    )

    # Config fetchable through the config API (what the UI's editor loads).
    config = ha.list_remote("automation")["ui_editable"]
    assert config["id"] == "ui_editable"
    assert config["alias"] == "UI Editable Automation"

    # Entity registry: an automation entity exists with unique_id == config id.
    entries = ha.entity_registry()
    matching = [
        e
        for e in entries
        if e.get("platform") == "automation" and e.get("unique_id") == "ui_editable"
    ]
    assert len(matching) == 1, (
        "expected exactly one registry entry with unique_id == config id (I2)"
    )
    assert matching[0]["entity_id"].startswith("automation.")
