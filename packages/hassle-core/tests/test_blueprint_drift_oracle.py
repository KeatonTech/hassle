"""The substitute-compare drift oracle (blueprints-design §2.2 / §3).

HA cannot serve a blueprint's source back, so text comparison is impossible.
What IS possible: ask HA to expand its own copy with a known input set
(``blueprint/substitute``), expand the bundle's copy locally with the same
inputs, normalize, compare. Equal expansions mean the two copies agree in
every way that can matter to an instance.

§3 pins where the inputs come from: **one of the blueprint's own instances in
the bundle** — any instance covers all required inputs, or validate would have
failed (§6) — and a blueprint with **no** instances skips the check entirely,
because nothing can be affected by its drift.
"""

from __future__ import annotations

from typing import Any

from hassle.backend.fake import FakeBackend
from hassle.blueprints import blueprint_body, instances_by_blueprint
from hassle.ir import BLUEPRINT_KIND
from hassle.sync.blueprint_drift import detect_blueprint_drift

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    switch_entity:
    room_light:
mode: restart
triggers:
  - trigger: state
    entity_id: !input switch_entity
actions:
  - action: light.turn_on
    target:
      entity_id: !input room_light
"""

PATH = "local/room-switch-controls.yaml"
KEY = f"blueprint:automation/{PATH}"

INSTANCE = {
    "id": "office_switch",
    "use_blueprint": {
        "path": PATH,
        "input": {"switch_entity": "event.office", "room_light": "light.office"},
    },
}


def _local(source: str = SOURCE) -> dict[str, Any]:
    return blueprint_body(domain="automation", path=PATH, source=source)


def _objects(*, source: str = SOURCE, with_instance: bool = True) -> dict[str, Any]:
    objects: dict[str, Any] = {KEY: (BLUEPRINT_KIND, _local(source))}
    if with_instance:
        objects["automation:office_switch"] = ("automation", INSTANCE)
    return objects


def _backend(source: str = SOURCE) -> FakeBackend:
    backend = FakeBackend()
    backend.create(BLUEPRINT_KIND, _local(source))
    return backend


# --- instances_by_blueprint ------------------------------------------------


def test_instances_are_found_by_their_use_blueprint_path() -> None:
    bodies = {"automation:office_switch": INSTANCE}
    assert instances_by_blueprint(bodies) == {KEY: ["automation:office_switch"]}


def test_instances_are_grouped_and_ordered_deterministically() -> None:
    bodies = {
        "automation:b": INSTANCE,
        "automation:a": INSTANCE,
    }
    assert instances_by_blueprint(bodies) == {KEY: ["automation:a", "automation:b"]}


def test_an_automation_with_no_use_blueprint_is_ignored() -> None:
    assert instances_by_blueprint({"automation:plain": {"id": "plain", "triggers": []}}) == {}


def test_a_community_blueprint_path_still_maps_to_its_would_be_key() -> None:
    """An instance of a blueprint that lives only in HA has no bundle file --
    but its key is still derivable, which is what lets §6's rule 2 name the
    file that WOULD make it managed."""
    body = {"id": "x", "use_blueprint": {"path": "jay-kub/taps.yaml", "input": {}}}
    assert instances_by_blueprint({"automation:x": body}) == {
        "blueprint:automation/jay-kub/taps.yaml": ["automation:x"]
    }


# --- detect_blueprint_drift ------------------------------------------------


def test_agreeing_copies_report_no_drift() -> None:
    assert detect_blueprint_drift(_backend(), _objects()) == frozenset()


def test_a_remotely_edited_blueprint_is_detected() -> None:
    """The whole point: the two documents' TEXT can't be compared, but their
    behaviour can."""
    backend = _backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(SOURCE.replace("light.turn_on", "light.toggle")),
    )
    assert detect_blueprint_drift(backend, _objects()) == frozenset({KEY})


def test_a_blueprint_with_no_instances_is_skipped() -> None:
    """§3: "a blueprint with no instances skips the check (nothing can be
    affected by drift)" -- and there would be no input set to substitute
    with anyway."""
    backend = _backend()
    backend.update(
        BLUEPRINT_KIND,
        f"automation/{PATH}",
        _local(SOURCE.replace("light.turn_on", "light.toggle")),
    )
    assert detect_blueprint_drift(backend, _objects(with_instance=False)) == frozenset()


def test_a_blueprint_that_is_not_remote_yet_is_skipped() -> None:
    """Nothing to compare against: a `create` row has no remote copy."""
    assert detect_blueprint_drift(FakeBackend(), _objects()) == frozenset()


def test_normalization_differences_are_not_drift() -> None:
    """A blueprint authored in HA's legacy singular schema expands to the same
    automation as its plural twin. Comparing raw expansions would report
    permanent, unfixable drift for every legacy blueprint."""
    legacy = SOURCE.replace("triggers:", "trigger:").replace("actions:", "action:")
    legacy = legacy.replace("  - action: light.turn_on", "  - service: light.turn_on")
    backend = _backend(legacy)
    assert detect_blueprint_drift(backend, _objects(source=legacy)) == frozenset()


def test_a_backend_without_substitute_reports_nothing() -> None:
    """Additive, `getattr`-probed surface: a Backend implementer that doesn't
    expose `blueprint_substitute` simply skips the corroboration, exactly as
    one without `entry_id_for` gets `entry_id=None` forever."""

    class _Bare:
        def list_remote(self, kind: str) -> dict[str, dict[str, Any]]:
            return {}

    assert detect_blueprint_drift(_Bare(), _objects()) == frozenset()


def test_a_failing_substitute_is_not_reported_as_drift() -> None:
    """The oracle CORROBORATES; it must never invent a conflict out of a
    transport hiccup or an input set HA rejects. A failure means "unknown",
    and unknown is not drift (the manifest hash still governs)."""

    class _Exploding(FakeBackend):
        def blueprint_substitute(
            self, domain: str, path: str, inputs: dict[str, Any]
        ) -> dict[str, Any]:
            raise RuntimeError("boom")

    backend = _Exploding()
    backend.create(BLUEPRINT_KIND, _local())
    assert detect_blueprint_drift(backend, _objects()) == frozenset()
