"""Capture-driven backend tests for the config-entry group-helper domain
(docs/ha-api-notes.md §38).

`FakeBackend` models the multi-step config-entry flow (create: menu step
choosing the flavor, then a form step -> `create_entry`) and options-flow
(update: one form step -> `create_entry`, same `entry_id`) shapes, mirroring
the template-helper flow tests (`test_fake_backend_template_flow.py`) --
this suite is transport-agnostic: it exercises the SAME `Backend.create`/
`update`/`delete`/`list_remote` methods every other kind uses (the frozen
SourceWriter/plan seam untouched).

**Identity (§38.1):** there is no `unique_id` -- identity is derived from
`name` (slugified), same as template helpers.

**The group options-flow schema does NOT include `name`, same as template**
(docs/ha-api-notes.md §38.1): submitting an options-flow update that carries
`name` produces a real HA 400,
`{"errors": {"base": ["extra keys not allowed @ data['name']"]}}`, on both
`stable` and `dev`. A group's title is simply not editable through the
options flow -- exactly like template, a rename is an identity change
(delete+create), never an in-place update. `update()` strips `name` at the
public-API boundary before it ever reaches the simulated options-flow
submission (mirroring `_update_via_options_flow` above byte-for-byte).
"""

from __future__ import annotations

import pytest

from hassle.backend.fake import ConfigEntryFlowError, FakeBackend

GROUP_DOMAINS = (
    "group_binary_sensor",
    "group_button",
    "group_cover",
    "group_event",
    "group_fan",
    "group_light",
    "group_lock",
    "group_media_player",
    "group_notify",
    "group_sensor",
    "group_switch",
    "group_valve",
)


def _extra_fields(domain: str) -> dict[str, object]:
    """The extra field each domain's form schema requires/accepts beyond
    name/entities/hide_members (docs/ha-api-notes.md §38.1)."""
    if domain == "group_sensor":
        return {"type": "mean"}
    if domain in ("group_binary_sensor", "group_light", "group_switch"):
        return {"all": False}
    return {}


def test_group_cover_create_drives_menu_then_form_then_create_entry() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover",
        {
            "name": "Entryway Top",
            "entities": ["cover.a", "cover.b"],
            "hide_members": False,
        },
    )
    assert identity == "entryway_top"

    steps = backend.flow_log
    assert len(steps) == 3
    menu, form, result = steps
    assert menu.type == "menu"
    assert menu.step_id == "user"
    assert len(menu.menu_options) == 12
    assert "cover" in menu.menu_options
    assert form.type == "form"
    assert form.step_id == "cover"
    assert form.flow_id == menu.flow_id
    assert "unique_id" not in form.data_schema
    assert result.type == "create_entry"
    assert result.flow_id == menu.flow_id
    assert result.result is not None
    assert result.result["title"] == "Entryway Top"
    assert result.result["options"]["entities"] == ["cover.a", "cover.b"]
    assert "unique_id" not in result.result["options"]


def test_group_cover_create_assigns_entry_id_never_caller_supplied() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    entry_id = backend.entry_id_for("group_cover", identity)
    assert entry_id is not None
    assert entry_id.startswith("entry_")


def test_group_cover_list_remote_returns_stored_options() -> None:
    backend = FakeBackend()
    backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True}
    )
    stored = backend.list_remote("group_cover")["top"]
    assert stored["name"] == "Top"
    assert stored["entities"] == ["cover.a", "cover.b"]
    assert stored["hide_members"] is True
    assert "unique_id" not in stored


def test_group_cover_update_drives_options_flow_same_entry_id() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    entry_id_before = backend.entry_id_for("group_cover", identity)
    backend.reset_write_tracking()
    log_len_before = len(backend.flow_log)

    # `name` is NOT resubmitted (docs/ha-api-notes.md §38.1, CI-corrected --
    # the options-flow schema never includes it; real HA 400s if it's sent).
    backend.update(
        "group_cover",
        identity,
        {"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
    )

    entry_id_after = backend.entry_id_for("group_cover", identity)
    assert entry_id_after == entry_id_before

    stored = backend.list_remote("group_cover")[identity]
    assert stored["entities"] == ["cover.a", "cover.b"]
    assert stored["hide_members"] is True
    # `name` survives an update it was never resubmitted in (merged from the
    # existing stored options, same as template §26.7 finding 3).
    assert stored["name"] == "Top"

    new_steps = backend.flow_log[log_len_before:]
    assert len(new_steps) == 2
    form, result = new_steps
    assert form.type == "form"
    assert "unique_id" not in form.data_schema
    assert "name" not in form.data_schema
    assert result.type == "create_entry"
    assert result.result is not None
    assert result.result["entry_id"] == entry_id_before


def test_group_cover_update_silently_strips_name_at_the_public_api_boundary() -> None:
    # `update()` (the `Backend`-protocol-facing method) still takes the
    # FULL local config, exactly like every other kind -- `name` is stripped
    # before it ever reaches the simulated options-flow submission, mirroring
    # `DirectBackend._aupdate_group_helper` protecting a caller from ever
    # producing the real HA 400 (docs/ha-api-notes.md §38.1). A caller must
    # never see this as an error.
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    backend.update(
        "group_cover",
        identity,
        {"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
    )
    stored = backend.list_remote("group_cover")[identity]
    assert stored["entities"] == ["cover.a", "cover.b"]
    assert stored["name"] == "Top"


def test_group_cover_internal_options_flow_submission_rejects_name_field() -> None:
    # The internal flow-submission step itself (mirroring the real
    # options-flow schema, docs/ha-api-notes.md §38.1) must reject `name` if
    # it ever reached it -- `update()`'s stripping (previous test) is what
    # actually prevents this in practice; this test pins the lower-level
    # simulation's fidelity to the real 400 directly.
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    with pytest.raises(ConfigEntryFlowError, match="name"):
        backend._update_group_via_options_flow(  # type: ignore[attr-defined]
            "group_cover",
            identity,
            {"name": "Top", "entities": ["cover.a", "cover.b"], "hide_members": True},
        )


def test_group_cover_update_preserves_name_without_resubmitting_it() -> None:
    # Real HA merges the update's fields into the entry's EXISTING options
    # rather than replacing the dict outright (mirrors template §26.7
    # finding 3) -- `name` (never part of the options-flow schema) survives
    # untouched across an update that never resubmits it.
    backend = FakeBackend()
    identity = backend.create(
        "group_cover",
        {"name": "Entryway Top", "entities": ["cover.a"], "hide_members": False},
    )
    backend.update(
        "group_cover",
        identity,
        {"entities": ["cover.a", "cover.b"], "hide_members": True},
    )
    stored = backend.list_remote("group_cover")[identity]
    assert stored["name"] == "Entryway Top"
    assert stored["entities"] == ["cover.a", "cover.b"]


def test_group_cover_delete_is_entry_removal() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    backend.delete("group_cover", identity)
    assert identity not in backend.list_remote("group_cover")
    assert backend.entry_id_for("group_cover", identity) is None


def test_group_cover_recreate_after_delete_gets_fresh_entry_id() -> None:
    # Rollback caveat parity with the template-helper flow (docs/ha-api-notes.md
    # §38 mirrors §26.3): a DELETE then re-CREATE under the same name-derived
    # identity is NOT the same HA object -- a fresh entry_id is assigned.
    backend = FakeBackend()
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    first_entry_id = backend.entry_id_for("group_cover", identity)
    backend.delete("group_cover", identity)
    backend.create("group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False})
    second_entry_id = backend.entry_id_for("group_cover", identity)
    assert second_entry_id != first_entry_id


def test_group_create_collision_raises() -> None:
    backend = FakeBackend()
    backend.create("group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False})
    with pytest.raises(ConfigEntryFlowError):
        backend.create(
            "group_cover", {"name": "Top", "entities": ["cover.b"], "hide_members": False}
        )


def test_group_update_unknown_identity_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="no config entry tracked"):
        backend.update(
            "group_cover",
            "nonexistent",
            {"name": "nonexistent", "entities": ["cover.a"], "hide_members": False},
        )


def test_group_create_without_name_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="name"):
        backend.create("group_cover", {"entities": ["cover.a"], "hide_members": False})


@pytest.mark.parametrize("domain", GROUP_DOMAINS)
def test_every_group_domain_supports_full_cycle(domain: str) -> None:
    backend = FakeBackend()
    extra = _extra_fields(domain)
    identity = backend.create(
        domain, {"name": "Thing", "entities": ["x.a"], "hide_members": False, **extra}
    )
    assert backend.list_remote(domain)[identity]["name"] == "Thing"
    backend.update(
        domain,
        identity,
        {"name": "Thing", "entities": ["x.a", "x.b"], "hide_members": True, **extra},
    )
    updated = backend.list_remote(domain)[identity]
    assert updated["entities"] == ["x.a", "x.b"]
    assert updated["hide_members"] is True
    assert updated["name"] == "Thing"
    backend.delete(domain, identity)
    assert identity not in backend.list_remote(domain)


def test_group_sensor_create_missing_type_raises() -> None:
    backend = FakeBackend()
    with pytest.raises(ConfigEntryFlowError, match="type"):
        backend.create(
            "group_sensor", {"name": "No Type", "entities": ["sensor.a"], "hide_members": False}
        )


def test_group_sensor_update_missing_type_raises() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "group_sensor",
        {"name": "Avg", "entities": ["sensor.a"], "hide_members": False, "type": "mean"},
    )
    with pytest.raises(ConfigEntryFlowError, match="type"):
        backend.update(
            "group_sensor",
            identity,
            {"name": "Avg", "entities": ["sensor.a", "sensor.b"], "hide_members": False},
        )


def test_group_flavors_without_all_do_not_require_it() -> None:
    # button/cover/event/fan/lock/media_player/notify/valve: no `all=` field.
    backend = FakeBackend()
    backend.create(
        "group_cover", {"name": "Just Cover", "entities": ["cover.a"], "hide_members": False}
    )
    assert "just_cover" in backend.list_remote("group_cover")


def test_group_menu_offers_all_twelve_flavors() -> None:
    backend = FakeBackend()
    backend.create("group_cover", {"name": "T", "entities": ["cover.a"], "hide_members": False})
    menu_step = backend.flow_log[0]
    assert set(menu_step.menu_options) == {
        "binary_sensor",
        "button",
        "cover",
        "event",
        "fan",
        "light",
        "lock",
        "media_player",
        "notify",
        "sensor",
        "switch",
        "valve",
    }


def test_group_writes_counted_like_any_other_kind() -> None:
    backend = FakeBackend()
    assert backend.writes_since_reset() == 0
    identity = backend.create(
        "group_cover", {"name": "Top", "entities": ["cover.a"], "hide_members": False}
    )
    assert backend.writes_since_reset() == 1
    backend.update(
        "group_cover", identity, {"name": "Top", "entities": ["cover.a"], "hide_members": True}
    )
    assert backend.writes_since_reset() == 2
    backend.delete("group_cover", identity)
    assert backend.writes_since_reset() == 3


def test_group_entry_ids_are_separate_from_template_entry_ids() -> None:
    # A separate bookkeeping dict from TEMPLATE_DOMAINS' -- no cross-talk.
    backend = FakeBackend()
    backend.create(
        "group_cover", {"name": "Shared Name", "entities": ["cover.a"], "hide_members": False}
    )
    assert backend.entry_id_for("template_number", "shared_name") is None
