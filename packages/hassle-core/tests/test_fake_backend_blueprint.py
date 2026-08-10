"""`FakeBackend`'s blueprint store (blueprints-design §2/§7).

The four commands §2 probed live, modelled with their probed semantics:

- ``blueprint/list`` — **metadata only**. HA cannot serve a blueprint's source
  back (§2.1), and the fake must not either: `list_remote("blueprint")` returns
  ``{"domain", "path", "metadata"}`` and NEVER a ``source`` key, however much
  of the document the fake happens to be holding internally. That asymmetry is
  the single fact the whole plan table (§3) is shaped around, so a fake that
  leaked the source would let a wrong plan engine pass.
- ``blueprint/save`` — create and update both.
- ``blueprint/delete`` — errors on a missing path.
- ``blueprint/substitute`` — expands **against the fake's own stored YAML**,
  through `hassle.blueprints` (§7: one expansion implementation everywhere).
  A substitute that re-ran the caller's local copy would make the §2.2 drift
  oracle circular and incapable of detecting anything.
"""

from __future__ import annotations

from typing import Any

import pytest

from hassle.backend.fake import FakeBackend
from hassle.blueprints import MissingBlueprintInputError, blueprint_body
from hassle.ir import BLUEPRINT_KIND

SOURCE = """\
blueprint:
  name: Room Switch Controls
  description: One paddle, one room.
  domain: automation
  input:
    switch_entity:
      name: Switch
    room_light:
      name: Room light
    dim_step_pct:
      name: Dim step
      default: 10
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions:
  - action: light.turn_on
    target:
      entity_id: !input room_light
    data:
      brightness_step_pct: !input dim_step_pct
"""

PATH = "local/room-switch-controls.yaml"
IDENTITY = f"automation/{PATH}"


def _body(source: str = SOURCE, *, path: str = PATH, domain: str = "automation") -> dict[str, Any]:
    return blueprint_body(domain=domain, path=path, source=source)


def _seeded() -> FakeBackend:
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _body())
    return backend


# --- blueprint/save (create) ----------------------------------------------


def test_create_returns_the_domain_slash_path_identity() -> None:
    assert FakeBackend().create(BLUEPRINT_KIND, _body()) == IDENTITY


def test_create_makes_it_visible_to_list() -> None:
    assert IDENTITY in _seeded().list_remote(BLUEPRINT_KIND)


def test_create_rejects_a_second_blueprint_at_the_same_path() -> None:
    """`allow_override: False` on a create -- the plan said nothing was there
    (§3's `create` row), so something appearing since is drift, not a silent
    overwrite."""
    backend = _seeded()
    with pytest.raises(ValueError, match="already exists"):
        backend.create(BLUEPRINT_KIND, _body(SOURCE.replace("Room", "Other")))


def test_create_rejects_a_body_with_no_source() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="source"):
        backend.create(BLUEPRINT_KIND, {"domain": "automation", "path": PATH})


# --- blueprint/list (metadata only) ---------------------------------------


def test_list_never_returns_the_source() -> None:
    """§2.1, the fact everything downstream is shaped around: HA has no
    command that serves a blueprint's source back."""
    listed = _seeded().list_remote(BLUEPRINT_KIND)[IDENTITY]
    assert "source" not in listed
    assert "inputs" not in listed


def test_list_returns_the_blueprint_block_as_metadata() -> None:
    listed = _seeded().list_remote(BLUEPRINT_KIND)[IDENTITY]
    assert listed["domain"] == "automation"
    assert listed["path"] == PATH
    metadata = listed["metadata"]
    assert metadata["name"] == "Room Switch Controls"
    assert metadata["description"] == "One paddle, one room."
    assert set(metadata["input"]) == {"switch_entity", "room_light", "dim_step_pct"}


def test_list_is_a_copy_not_the_store() -> None:
    backend = _seeded()
    backend.list_remote(BLUEPRINT_KIND)[IDENTITY]["metadata"] = {"tampered": True}
    assert backend.list_remote(BLUEPRINT_KIND)[IDENTITY]["metadata"]["name"] == (
        "Room Switch Controls"
    )


def test_list_is_empty_when_nothing_was_saved() -> None:
    assert FakeBackend().list_remote(BLUEPRINT_KIND) == {}


# --- blueprint/save (update) ----------------------------------------------


def test_update_replaces_the_stored_source() -> None:
    backend = _seeded()
    edited = SOURCE.replace("Room Switch Controls", "Room Switch Controls v2")
    backend.update(BLUEPRINT_KIND, IDENTITY, _body(edited))
    assert backend.blueprint_source(IDENTITY) == edited
    assert backend.list_remote(BLUEPRINT_KIND)[IDENTITY]["metadata"]["name"] == (
        "Room Switch Controls v2"
    )


def test_update_of_an_unknown_path_raises() -> None:
    """Fidelity with the helper/dashboard guards: an UPDATE never upserts, so
    apply's rollback can never quietly paper over a recreate that should have
    gone through `create`."""
    backend = FakeBackend()
    with pytest.raises(ValueError, match=r"local/room-switch-controls\.yaml"):
        backend.update(BLUEPRINT_KIND, IDENTITY, _body())


# --- blueprint/delete ------------------------------------------------------


def test_delete_removes_the_blueprint_and_its_source() -> None:
    backend = _seeded()
    backend.delete(BLUEPRINT_KIND, IDENTITY)
    assert backend.list_remote(BLUEPRINT_KIND) == {}
    assert backend.blueprint_source(IDENTITY) is None


def test_delete_of_a_missing_path_errors() -> None:
    """§2: real HA answers `unknown_error`/ENOENT for a missing path -- an
    error, not a silent success (still distinguishable from
    `unknown_command`)."""
    with pytest.raises(ValueError, match=r"local/nope\.yaml"):
        FakeBackend().delete(BLUEPRINT_KIND, "automation/local/nope.yaml")


# --- blueprint/substitute (the §2.2 drift oracle) --------------------------


def test_substitute_expands_against_the_stored_yaml() -> None:
    expanded = _seeded().blueprint_substitute(
        "automation", PATH, {"switch_entity": "event.office", "room_light": "light.office"}
    )
    assert expanded["mode"] == "restart"
    assert expanded["triggers"] == [{"trigger": "state", "entity_id": "event.office"}]
    assert expanded["actions"] == [
        {
            "action": "light.turn_on",
            "target": {"entity_id": "light.office"},
            "data": {"brightness_step_pct": 10},
        }
    ]


def test_substitute_reflects_a_remote_edit_not_the_callers_copy() -> None:
    """The whole point of the oracle (§2.2): substitute must answer from HA's
    OWN copy, so a remote in-place edit shows up as a mismatch. A fake that
    expanded whatever the caller passed would detect nothing, forever."""
    backend = _seeded()
    backend.update(BLUEPRINT_KIND, IDENTITY, _body(SOURCE.replace("restart", "single")))
    expanded = backend.blueprint_substitute(
        "automation", PATH, {"switch_entity": "event.office", "room_light": "light.office"}
    )
    assert expanded["mode"] == "single"


def test_substitute_validates_required_inputs() -> None:
    """§2: `blueprint/substitute` validates required inputs, and its error
    enumerates the missing ones."""
    with pytest.raises(MissingBlueprintInputError) as excinfo:
        _seeded().blueprint_substitute("automation", PATH, {"switch_entity": "event.office"})
    assert "room_light" in str(excinfo.value)


def test_substitute_of_an_unknown_path_raises() -> None:
    with pytest.raises(ValueError, match=r"local/nope\.yaml"):
        FakeBackend().blueprint_substitute("automation", "local/nope.yaml", {})


def test_substitute_uses_the_shared_expansion_implementation() -> None:
    """§7: ONE expansion implementation everywhere. The fake's answer must
    equal what `hassle.blueprints.expand_blueprint` produces locally from the
    same YAML and the same inputs -- that equality is exactly what the drift
    check compares, so it has to hold when the two copies agree."""
    from pathlib import Path as _Path
    from tempfile import TemporaryDirectory

    from hassle.blueprints import blueprint_file, expand_blueprint

    inputs = {"switch_entity": "event.office", "room_light": "light.office"}
    remote = _seeded().blueprint_substitute("automation", PATH, inputs)

    with TemporaryDirectory() as tmp:
        root = _Path(tmp)
        target = blueprint_file(root, PATH)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(SOURCE, encoding="utf-8")
        local = expand_blueprint(
            {"id": "office", "use_blueprint": {"path": PATH, "input": inputs}},
            bundle_root=root,
        )
    assert local is not None
    # `expand_blueprint` additionally carries the instance's own id/alias
    # across (that is the instance's half); the blueprint's own half must
    # match exactly.
    assert {k: v for k, v in local.items() if k != "id"} == remote


# --- store bookkeeping -----------------------------------------------------


def test_snapshot_and_restore_round_trip_the_source() -> None:
    """apply's rollback restores from `Backend` calls, so a blueprint that
    round-tripped only its metadata would be silently unrecoverable."""
    backend = _seeded()
    snapshot = backend.snapshot(BLUEPRINT_KIND)
    backend.delete(BLUEPRINT_KIND, IDENTITY)
    backend.restore(BLUEPRINT_KIND, snapshot)
    assert backend.blueprint_source(IDENTITY) == SOURCE


def test_script_domain_blueprints_key_separately() -> None:
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _body())
    backend.create(BLUEPRINT_KIND, _body(domain="script"))
    assert set(backend.list_remote(BLUEPRINT_KIND)) == {
        f"automation/{PATH}",
        f"script/{PATH}",
    }


def test_reload_automations_is_recorded() -> None:
    """§4.3's post-update reload. Additive and non-Protocol, probed via
    `getattr` the way `entry_id_for` is."""
    backend = FakeBackend()
    assert backend.automation_reloads == 0
    backend.reload_automations()
    assert backend.automation_reloads == 1
