"""Capture-driven backend tests for the config-entry template-helper domain.

`FakeBackend` models the multi-step config-entry flow (create: menu step
choosing the template type, then a form step -> `create_entry`) and
options-flow (update: one form step -> `create_entry`, same `entry_id`)
shapes (docs/ha-api-notes.md §26; the REAL transport was captured by the CI
integration suite, `packages/hassle-core/tests/integration/
test_live_template_flow.py`, which is the authoritative verification -- it
found the flow/options-flow/removal operations are REST, not WebSocket, §26.0,
AND that the form schema rejects `unique_id`/bookkeeping keys and requires
domain-specific write-target fields, §26.6). This suite is transport-agnostic:
it exercises the SAME `Backend.create`/`update`/`delete`/`list_remote` methods
every other kind uses (the frozen SourceWriter/plan seam untouched) while
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

    # `name` is NOT resubmitted (docs/ha-api-notes.md §26.7 -- the
    # options-flow schema never includes it; real HA 400s if it's sent).
    backend.update(
        "template_number",
        identity,
        {"state": "{{ 2 }}", "set_value": _SET_VALUE, "min": 0, "max": 10},
    )

    entry_id_after = backend.entry_id_for("template_number", identity)
    # Analogous to never changing an existing object's HA id: the entry_id is
    # UNCHANGED across an update (never a recreate).
    assert entry_id_after == entry_id_before

    stored = backend.list_remote("template_number")[identity]
    assert stored["state"] == "{{ 2 }}"
    assert stored["max"] == 10
    # `name` survives an update it was never resubmitted in (§26.7 finding 3).
    assert stored["name"] == "Zones"

    new_steps = backend.flow_log[log_len_before:]
    assert len(new_steps) == 2
    form, result = new_steps
    assert form.type == "form"
    assert "unique_id" not in form.data_schema
    assert "name" not in form.data_schema
    assert result.type == "create_entry"
    assert result.result is not None
    assert result.result["entry_id"] == entry_id_before


def test_template_number_update_silently_strips_name_at_the_public_api_boundary() -> None:
    # `update()` (the `Backend`-protocol-facing method) still takes the
    # FULL local config, exactly like every other kind -- `name` is stripped
    # before it ever reaches the simulated options-flow submission, mirroring
    # `DirectBackend._aupdate_template_helper` protecting a caller from ever
    # producing the real HA 400 (docs/ha-api-notes.md §26.7). A caller must
    # never see this as an error: nothing else in Hassle strips `name` out of
    # the local config before calling `Backend.update`.
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    backend.update(
        "template_number",
        identity,
        {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
    )
    stored = backend.list_remote("template_number")[identity]
    assert stored["state"] == "{{ 2 }}"
    assert stored["name"] == "Zones"


def test_template_number_internal_options_flow_submission_rejects_name_field() -> None:
    # The internal flow-submission step itself (mirroring the real
    # options-flow schema, docs/ha-api-notes.md §26.7 finding 2) must reject
    # `name` if it ever reached it -- `update()`'s stripping (previous test)
    # is what actually prevents this in practice; this test pins the
    # lower-level simulation's fidelity to the real 400 directly.
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    with pytest.raises(ConfigEntryFlowError, match="name"):
        backend._update_via_options_flow(  # type: ignore[attr-defined]
            "template_number",
            identity,
            {"name": "Zones", "state": "{{ 2 }}", "set_value": _SET_VALUE},
        )


def test_template_number_update_preserves_name_without_resubmitting_it() -> None:
    # Real HA merges the update's fields into the entry's EXISTING options
    # rather than replacing the dict outright (docs/ha-api-notes.md §26.7
    # finding 3) -- `name` (never part of the options-flow schema) survives
    # untouched across an update that never resubmits it.
    backend = FakeBackend()
    identity = backend.create(
        "template_number",
        {
            "name": "Active HVAC Zones",
            "state": "{{ 1 }}",
            "set_value": _SET_VALUE,
            "min": 0,
            "max": 8,
        },
    )
    backend.update(
        "template_number",
        identity,
        {"state": "{{ 2 }}", "set_value": _SET_VALUE, "min": 0, "max": 8},
    )
    stored = backend.list_remote("template_number")[identity]
    assert stored["name"] == "Active HVAC Zones"
    assert stored["state"] == "{{ 2 }}"


def test_template_number_delete_is_entry_removal() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"name": "Zones", "state": "{{ 1 }}", "set_value": _SET_VALUE}
    )
    backend.delete("template_number", identity)
    assert identity not in backend.list_remote("template_number")
    assert backend.entry_id_for("template_number", identity) is None


def test_template_number_recreate_after_delete_gets_fresh_entry_id() -> None:
    # Documents the entry_id-changes rollback caveat: a DELETE then re-CREATE
    # under the same name-derived identity is NOT the
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
    # `name` is NOT part of an UPDATE's payload (docs/ha-api-notes.md §26.7 --
    # the options-flow schema never includes it); it survives untouched.
    backend.update(domain, identity, {"state": "{{ 2 }}", **extra})
    updated = backend.list_remote(domain)[identity]
    assert updated["state"] == "{{ 2 }}"
    assert updated["name"] == "Thing"
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
        {"state": "{{ 2 }}", "set_value": _SET_VALUE},
    )
    assert backend.writes_since_reset() == 2
    backend.delete("template_number", identity)
    assert backend.writes_since_reset() == 3
