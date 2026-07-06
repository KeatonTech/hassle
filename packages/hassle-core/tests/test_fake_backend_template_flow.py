"""MILESTONES M10 test 1 — capture-driven backend tests for the config-entry
template-helper domain.

`FakeBackend` models the multi-step config-entry flow (create: menu step
choosing the template type, then a form step -> `create_entry`) and
options-flow (update: one form step -> `create_entry`, same `entry_id`)
shapes (docs/ha-api-notes.md §26; the REAL transport was captured by the CI
integration suite, `packages/hassle-core/tests/integration/
test_m10_template_flow.py`, which is the authoritative verification per
MILESTONES M10 — it found the flow/options-flow/removal operations are REST,
not WebSocket, §26.0, AND that the form schema rejects `unique_id`/bookkeeping
keys and requires domain-specific write-target fields, §26.6). This suite is
transport-agnostic: it exercises the SAME `Backend.create`/`update`/
`delete`/`list_remote` methods every other kind uses (F2 untouched) while
asserting on the internal flow-step log FakeBackend records for test
visibility.

**Identity (§26.6):** there is no `unique_id` -- the real form schema rejects
it as an unrecognized key. Identity is derived from `name` (slugified),
mirroring the storage helpers' "id is a slug of name" rule.
"""

from __future__ import annotations

import pytest

from hassle.backend.fake import ConfigEntryFlowError, FakeBackend

TEMPLATE_DOMAINS = (
    "template_number",
    "template_sensor",
    "template_binary_sensor",
    "template_select",
)

_SET_VALUE = {"action": "input_number.set_value", "data": {"value": "{{ value }}"}}
_SELECT_OPTION = {"action": "input_select.select_option", "data": {"option": "{{ option }}"}}


def _required_fields(domain: str) -> dict[str, object]:
    """The extra fields each domain's form schema requires beyond name/state
    (docs/ha-api-notes.md §26.6)."""
    if domain == "template_number":
        return {"set_value": _SET_VALUE}
    if domain == "template_select":
        return {"options": "{{ ['a', 'b'] }}", "select_option": _SELECT_OPTION}
    return {}


def test_template_number_create_drives_menu_then_form_then_create_entry() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number",
        {
            "name": "Active HVAC Zones",
            "state": "{{ 3 }}",
            "set_value": _SET_VALUE,
            "min": 0,
            "max": 8,
            "step": 1,
        },
    )
    assert identity == "active_hvac_zones"

    # The flow shape: menu -> form -> create_entry, all sharing one flow_id.
    steps = backend.flow_log
    assert len(steps) == 3
    menu, form, result = steps
    assert menu.type == "menu"
    assert menu.step_id == "user"
    assert "number" in menu.menu_options
    assert form.type == "form"
    assert form.step_id == "number"
    assert form.flow_id == menu.flow_id
    # The form submission never carries bookkeeping keys (§26.6 correction 1):
    # no `unique_id`, no `_template_type`.
    assert "unique_id" not in form.data_schema
    assert "_template_type" not in form.data_schema
    assert result.type == "create_entry"
    assert result.flow_id == menu.flow_id
    assert result.result is not None
    assert result.result["title"] == "Active HVAC Zones"
    assert result.result["options"]["state"] == "{{ 3 }}"
    assert "unique_id" not in result.result["options"]


def test_template_number_create_assigns_entry_id_never_caller_supplied() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    entry_id = backend.entry_id_for("template_number", identity)
    assert entry_id is not None
    assert entry_id.startswith("entry_")


def test_template_number_list_remote_returns_stored_options() -> None:
    backend = FakeBackend()
    backend.create(
        "template_number",
        {
            "name": "Zones",
            "state": "{{ 1 }}",
            "set_value": _SET_VALUE,
            "min": 0,
            "max": 5,
        },
    )
    stored = backend.list_remote("template_number")["zones"]
    assert stored["name"] == "Zones"
    assert stored["state"] == "{{ 1 }}"
    assert stored["min"] == 0
    assert stored["max"] == 5
    # No synthetic unique_id in the stored body (§26.6 -- there is none).
    assert "unique_id" not in stored


def test_template_number_update_drives_options_flow_same_entry_id() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    entry_id_before = backend.entry_id_for("template_number", identity)
    backend.reset_write_tracking()
    log_len_before = len(backend.flow_log)

    backend.update(
        "template_number",
        identity,
        {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE, "min": 0, "max": 10},
    )

    entry_id_after = backend.entry_id_for("template_number", identity)
    # I2 analog: the entry_id is UNCHANGED across an update (never a recreate).
    assert entry_id_after == entry_id_before

    stored = backend.list_remote("template_number")[identity]
    assert stored["state"] == "{{ 2 }}"
    assert stored["max"] == 10

    new_steps = backend.flow_log[log_len_before:]
    assert len(new_steps) == 2
    form, result = new_steps
    assert form.type == "form"
    assert "unique_id" not in form.data_schema
    assert result.type == "create_entry"
    assert result.result is not None
    assert result.result["entry_id"] == entry_id_before


def test_template_number_delete_is_entry_removal() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    backend.delete("template_number", identity)
    assert identity not in backend.list_remote("template_number")
    assert backend.entry_id_for("template_number", identity) is None


def test_template_number_recreate_after_delete_gets_fresh_entry_id() -> None:
    # Documents the entry_id-changes rollback caveat (MILESTONES M10 test 4):
    # a DELETE then re-CREATE under the same name-derived identity is NOT the
    # same HA object from HA's point of view -- a fresh entry_id is assigned.
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    first_entry_id = backend.entry_id_for("template_number", identity)
    backend.delete("template_number", identity)
    backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    second_entry_id = backend.entry_id_for("template_number", identity)
    assert second_entry_id != first_entry_id


def test_template_create_collision_raises() -> None:
    backend = FakeBackend()
    backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    with pytest.raises(ConfigEntryFlowError):
        backend.create(
            "template_number", {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE}
        )


def test_template_update_unknown_identity_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="no config entry tracked"):
        backend.update(
            "template_number",
            "nonexistent",
            {"name": "nonexistent", "state": "{{ 1 }}", "set_value": _SET_VALUE},
        )


@pytest.mark.parametrize("domain", TEMPLATE_DOMAINS)
def test_every_template_domain_supports_full_cycle(domain: str) -> None:
    backend = FakeBackend()
    extra = _required_fields(domain)
    identity = backend.create(domain, {"name": "Thing", "state": "{{ 1 }}", **extra})
    assert backend.list_remote(domain)[identity]["name"] == "Thing"
    # `name` in an UPDATE payload does not change the object key (the
    # identity Hassle tracks stays anchored to the identity `update` was
    # called with) even though the real entry's title/name field is what
    # got resubmitted -- this mirrors every other kind's update semantics
    # (addressed by identity, not re-derived from the new body).
    backend.update(domain, identity, {"name": "Thing", "state": "{{ 2 }}", **extra})
    assert backend.list_remote(domain)[identity]["state"] == "{{ 2 }}"
    backend.delete(domain, identity)
    assert identity not in backend.list_remote(domain)


def test_template_number_create_missing_set_value_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ConfigEntryFlowError, match="set_value"):
        backend.create("template_number", {"name": "No Write Target", "state": "{{ 1 }}"})


def test_template_select_create_missing_options_or_select_option_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ConfigEntryFlowError):
        backend.create("template_select", {"name": "No Options", "state": "{{ 1 }}"})
    with pytest.raises(ConfigEntryFlowError):
        backend.create(
            "template_select",
            {"name": "No Select Option", "state": "{{ 1 }}", "options": "{{ ['a'] }}"},
        )


def test_template_sensor_and_binary_sensor_need_no_write_target() -> None:
    # Read-only domains: `state` alone (plus `name`) is a complete, valid form.
    backend = FakeBackend()
    backend.create("template_sensor", {"name": "Average Temp", "state": "{{ 1 }}"})
    backend.create("template_binary_sensor", {"name": "Any Door Open", "state": "{{ 1 }}"})
    assert "average_temp" in backend.list_remote("template_sensor")
    assert "any_door_open" in backend.list_remote("template_binary_sensor")


def test_template_create_without_name_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="name"):
        backend.create("template_number", {"state": "{{ 1 }}", "set_value": _SET_VALUE})


def test_template_writes_counted_like_any_other_kind() -> None:
    backend = FakeBackend()
    assert backend.writes_since_reset() == 0
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    assert backend.writes_since_reset() == 1
    backend.update(
        "template_number",
        identity,
        {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
    )
    assert backend.writes_since_reset() == 2
    backend.delete("template_number", identity)
    assert backend.writes_since_reset() == 3
