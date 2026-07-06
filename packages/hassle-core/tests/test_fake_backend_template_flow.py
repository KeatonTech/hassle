"""MILESTONES M10 test 1 — capture-driven backend tests for the config-entry
template-helper domain.

`FakeBackend` models the multi-step `config_entries/flow` (create: menu step
choosing the template type, then a form step -> `create_entry`) and
`config_entries/options/flow` (update: one form step -> `create_entry`, same
`entry_id`) shapes (docs/ha-api-notes.md §26; the REAL shapes are captured by
the CI integration suite, `packages/hassle-core/tests/integration/
test_m10_template_flow.py`, which is the authoritative verification per
MILESTONES M10). This suite exercises the SAME `Backend.create`/`update`/
`delete`/`list_remote` methods every other kind uses (F2 untouched) while
asserting on the internal flow-step log FakeBackend records for test
visibility.
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


def test_template_number_create_drives_menu_then_form_then_create_entry() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number",
        {
            "unique_id": "active_hvac_zones",
            "name": "Active HVAC Zones",
            "state": "{{ 3 }}",
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
    assert result.type == "create_entry"
    assert result.flow_id == menu.flow_id
    assert result.result is not None
    assert result.result["unique_id"] == "active_hvac_zones"
    assert result.result["options"]["state"] == "{{ 3 }}"


def test_template_number_create_assigns_entry_id_never_caller_supplied() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"}
    )
    entry_id = backend.entry_id_for("template_number", identity)
    assert entry_id is not None
    assert entry_id.startswith("entry_")


def test_template_number_list_remote_returns_stored_options() -> None:
    backend = FakeBackend()
    backend.create(
        "template_number",
        {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}", "min": 0, "max": 5},
    )
    stored = backend.list_remote("template_number")["zones"]
    assert stored["name"] == "Zones"
    assert stored["state"] == "{{ 1 }}"
    assert stored["min"] == 0
    assert stored["max"] == 5
    # unique_id lives in the stored body (parity with HelperConfig storing `id`).
    assert stored["unique_id"] == "zones"


def test_template_number_update_drives_options_flow_same_entry_id() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"}
    )
    entry_id_before = backend.entry_id_for("template_number", identity)
    backend.reset_write_tracking()
    log_len_before = len(backend.flow_log)

    backend.update(
        "template_number",
        identity,
        {"unique_id": "zones", "name": "Zones", "state": "{{ 2 }}", "min": 0, "max": 10},
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
    assert result.type == "create_entry"
    assert result.result is not None
    assert result.result["entry_id"] == entry_id_before


def test_template_number_delete_is_entry_removal() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"}
    )
    backend.delete("template_number", identity)
    assert identity not in backend.list_remote("template_number")
    assert backend.entry_id_for("template_number", identity) is None


def test_template_number_recreate_after_delete_gets_fresh_entry_id() -> None:
    # Documents the entry_id-changes rollback caveat (MILESTONES M10 test 4):
    # a DELETE then re-CREATE under the same unique_id is NOT the same HA
    # object from HA's point of view -- a fresh entry_id is assigned.
    backend = FakeBackend()
    identity = backend.create(
        "template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"}
    )
    first_entry_id = backend.entry_id_for("template_number", identity)
    backend.delete("template_number", identity)
    backend.create("template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"})
    second_entry_id = backend.entry_id_for("template_number", identity)
    assert second_entry_id != first_entry_id


def test_template_create_collision_raises() -> None:
    backend = FakeBackend()
    backend.create("template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"})
    with pytest.raises(ConfigEntryFlowError):
        backend.create(
            "template_number", {"unique_id": "zones", "name": "Zones 2", "state": "{{ 2 }}"}
        )


def test_template_update_unknown_identity_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="no config entry tracked"):
        backend.update(
            "template_number", "nonexistent", {"unique_id": "nonexistent", "state": "{{ 1 }}"}
        )


@pytest.mark.parametrize("domain", TEMPLATE_DOMAINS)
def test_every_template_domain_supports_full_cycle(domain: str) -> None:
    backend = FakeBackend()
    identity = backend.create(domain, {"unique_id": "thing", "name": "Thing", "state": "{{ 1 }}"})
    assert backend.list_remote(domain)[identity]["name"] == "Thing"
    backend.update(domain, identity, {"unique_id": "thing", "name": "Thing 2", "state": "{{ 2 }}"})
    assert backend.list_remote(domain)[identity]["name"] == "Thing 2"
    backend.delete(domain, identity)
    assert identity not in backend.list_remote(domain)


def test_template_create_without_unique_id_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="unique_id"):
        backend.create("template_number", {"name": "No id", "state": "{{ 1 }}"})


def test_template_writes_counted_like_any_other_kind() -> None:
    backend = FakeBackend()
    assert backend.writes_since_reset() == 0
    identity = backend.create(
        "template_number", {"unique_id": "zones", "name": "Zones", "state": "{{ 1 }}"}
    )
    assert backend.writes_since_reset() == 1
    backend.update(
        "template_number", identity, {"unique_id": "zones", "name": "Zones 2", "state": "{{ 2 }}"}
    )
    assert backend.writes_since_reset() == 2
    backend.delete("template_number", identity)
    assert backend.writes_since_reset() == 3
